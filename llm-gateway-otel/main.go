// Tag 9: Variante mit OpenTelemetry-Tracing (otelhttp, OTLP/HTTP).
// llm-gateway: mandantenfähiger Reverse Proxy vor einem OpenAI-kompatiblen
// Modellserver (Ollama, llama.cpp, vLLM). Lab-Code aus "LLM-Plattformen zum Anfassen".
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
	"golang.org/x/time/rate"
)

var (
	requests = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "gateway_requests_total",
		Help: "Anfragen pro Mandant und Statuscode.",
	}, []string{"tenant", "code"})
	duration = prometheus.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "gateway_request_duration_seconds",
		Help:    "Gesamtdauer einer Anfrage inkl. Modellserver.",
		Buckets: []float64{0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60},
	}, []string{"tenant"})
	tokens = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "gateway_tokens_total",
		Help: "Tokens laut usage-Feld der Antwort.",
	}, []string{"tenant", "type"})
	limited = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "gateway_ratelimited_total",
		Help: "Wegen Rate-Limit abgewiesene Anfragen.",
	}, []string{"tenant"})
)

type ctxKey struct{}

// spanKey: Server-Span der Anfrage im Kontext (für countTokens).
type spanKey struct{}

// config liest alles aus Umgebungsvariablen (12-Factor).
type config struct {
	listen   string
	upstream *url.URL
	keys     map[string]string // API-Key -> Mandant
	rps      float64
	burst    int
}

func loadConfig() (config, error) {
	c := config{listen: env("LISTEN_ADDR", ":8080"), keys: map[string]string{}}
	u, err := url.Parse(env("UPSTREAM_URL", "http://127.0.0.1:11434"))
	if err != nil || u.Host == "" {
		return c, errors.New("UPSTREAM_URL ungültig")
	}
	c.upstream = u
	// TENANT_KEYS="acme:lab-key-acme,globex:lab-key-globex"
	for _, pair := range strings.Split(env("TENANT_KEYS", ""), ",") {
		tenant, key, ok := strings.Cut(strings.TrimSpace(pair), ":")
		if ok && tenant != "" && key != "" {
			c.keys[key] = tenant
		}
	}
	if len(c.keys) == 0 {
		return c, errors.New("TENANT_KEYS leer")
	}
	c.rps, err = strconv.ParseFloat(env("RATE_LIMIT_RPS", "5"), 64)
	if err != nil || c.rps <= 0 {
		return c, errors.New("RATE_LIMIT_RPS ungültig")
	}
	c.burst, err = strconv.Atoi(env("RATE_LIMIT_BURST", "10"))
	if err != nil || c.burst <= 0 {
		return c, errors.New("RATE_LIMIT_BURST ungültig")
	}
	return c, nil
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// setupTracing aktiviert den OTLP/HTTP-Export, wenn OTEL_EXPORTER_OTLP_ENDPOINT
// gesetzt ist. Endpunkt, Sampler und OTEL_SERVICE_NAME liest das SDK selbst.
func setupTracing(ctx context.Context) (func(context.Context) error, error) {
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{}, propagation.Baggage{}))
	if os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT") == "" {
		return func(context.Context) error { return nil }, nil // Tracing aus
	}
	exp, err := otlptracehttp.New(ctx)
	if err != nil {
		return nil, err
	}
	res, err := resource.New(ctx,
		resource.WithAttributes(attribute.String("service.name", "llm-gateway")),
		resource.WithFromEnv(), // OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES
		resource.WithTelemetrySDK())
	if err != nil {
		return nil, err
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exp), sdktrace.WithResource(res))
	otel.SetTracerProvider(tp)
	return tp.Shutdown, nil
}

// traceID liefert die Trace-ID aus dem Kontext (leer, wenn es keine gibt).
func traceID(ctx context.Context) string {
	if sc := trace.SpanContextFromContext(ctx); sc.HasTraceID() {
		return sc.TraceID().String()
	}
	return ""
}

// limiters hält einen Token-Bucket pro Mandant.
type limiters struct {
	mu    sync.Mutex
	rps   rate.Limit
	burst int
	m     map[string]*rate.Limiter
}

func (l *limiters) get(tenant string) *rate.Limiter {
	l.mu.Lock()
	defer l.mu.Unlock()
	lim, ok := l.m[tenant]
	if !ok {
		lim = rate.NewLimiter(l.rps, l.burst)
		l.m[tenant] = lim
	}
	return lim
}

// statusRecorder merkt sich den Statuscode für Metriken und Logs.
type statusRecorder struct {
	http.ResponseWriter
	code int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.code = code
	r.ResponseWriter.WriteHeader(code)
}

// Flush reicht gestreamte Antworten (stream=true) sofort an den Client durch.
func (r *statusRecorder) Flush() {
	if f, ok := r.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func newProxy(c config) *httputil.ReverseProxy {
	p := &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(c.upstream)
			pr.Out.Header.Del("Authorization") // Mandanten-Key nie an den Modellserver
			pr.Out.Header.Set("X-Tenant", pr.In.Context().Value(ctxKey{}).(string))
		},
		// Client-Span pro Upstream-Aufruf, traceparent-Header zum Modellserver
		Transport:      otelhttp.NewTransport(http.DefaultTransport),
		ModifyResponse: countTokens,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			slog.Error("upstream", "err", err, "trace_id", traceID(r.Context()))
			jsonError(w, "upstream unavailable", http.StatusBadGateway)
		},
	}
	return p
}

// countTokens liest usage.prompt_tokens/completion_tokens aus JSON-Antworten.
func countTokens(resp *http.Response) error {
	if !strings.HasPrefix(resp.Header.Get("Content-Type"), "application/json") {
		return nil // Streams (text/event-stream) werden nicht gepuffert
	}
	body, err := io.ReadAll(resp.Body)
	resp.Body.Close()
	if err != nil {
		return err
	}
	resp.Body = io.NopCloser(bytes.NewReader(body))
	var u struct {
		Usage struct {
			Prompt     int `json:"prompt_tokens"`
			Completion int `json:"completion_tokens"`
		} `json:"usage"`
	}
	if json.Unmarshal(body, &u) == nil {
		tenant := resp.Request.Context().Value(ctxKey{}).(string)
		tokens.WithLabelValues(tenant, "prompt").Add(float64(u.Usage.Prompt))
		tokens.WithLabelValues(tenant, "completion").Add(float64(u.Usage.Completion))
		// an den Server-Span: der Client-Span endet schon mit resp.Body.Close()
		if srv, ok := resp.Request.Context().Value(spanKey{}).(trace.Span); ok {
			srv.SetAttributes(
				attribute.Int("gen_ai.usage.input_tokens", u.Usage.Prompt),
				attribute.Int("gen_ai.usage.output_tokens", u.Usage.Completion))
		}
	}
	return nil
}

// jsonError antwortet wie OpenAI-kompatible APIs mit einem JSON-Fehlerobjekt.
func jsonError(w http.ResponseWriter, msg string, code int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

func gateway(c config, lim *limiters, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		key := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		tenant, ok := c.keys[key]
		if !ok {
			requests.WithLabelValues("unknown", "401").Inc()
			jsonError(w, "invalid api key", http.StatusUnauthorized)
			return
		}
		if !lim.get(tenant).Allow() {
			limited.WithLabelValues(tenant).Inc()
			requests.WithLabelValues(tenant, "429").Inc()
			w.Header().Set("Retry-After", "1")
			jsonError(w, "rate limit", http.StatusTooManyRequests)
			return
		}
		span := trace.SpanFromContext(r.Context()) // Server-Span von otelhttp
		span.SetAttributes(attribute.String("tenant", tenant))
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, code: http.StatusOK}
		ctx := context.WithValue(r.Context(), ctxKey{}, tenant)
		ctx = context.WithValue(ctx, spanKey{}, span)
		next.ServeHTTP(rec, r.WithContext(ctx))
		d := time.Since(start)
		duration.WithLabelValues(tenant).Observe(d.Seconds())
		requests.WithLabelValues(tenant, strconv.Itoa(rec.code)).Inc()
		slog.Info("request", "tenant", tenant, "method", r.Method, "path", r.URL.Path,
			"status", rec.code, "duration_ms", d.Milliseconds(),
			"trace_id", traceID(r.Context()))
	})
}

// ready prüft, ob der Modellserver antwortet (GET /v1/models).
func ready(c config) http.HandlerFunc {
	client := &http.Client{Timeout: 2 * time.Second}
	return func(w http.ResponseWriter, r *http.Request) {
		resp, err := client.Get(c.upstream.JoinPath("/v1/models").String())
		if err != nil {
			http.Error(w, "upstream not ready", http.StatusServiceUnavailable)
			return
		}
		resp.Body.Close() // auch bei Status != 200 schließen, sonst Verbindungsleck
		if resp.StatusCode != http.StatusOK {
			http.Error(w, "upstream not ready", http.StatusServiceUnavailable)
			return
		}
		io.WriteString(w, "ok\n")
	}
}

// newMux baut die Routen; otelhttp erzeugt einen Server-Span pro /v1-Anfrage.
func newMux(c config) http.Handler {
	lim := &limiters{rps: rate.Limit(c.rps), burst: c.burst,
		m: map[string]*rate.Limiter{}}
	mux := http.NewServeMux()
	mux.Handle("/v1/", gateway(c, lim, newProxy(c)))
	mux.Handle("GET /metrics", promhttp.Handler())
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, "ok\n")
	})
	mux.HandleFunc("GET /readyz", ready(c))
	return otelhttp.NewHandler(mux, "llm-gateway",
		otelhttp.WithFilter(func(r *http.Request) bool {
			return strings.HasPrefix(r.URL.Path, "/v1/") // keine Spans für Probes
		}),
		otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string {
			return r.Method + " " + r.URL.Path
		}))
}

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	prometheus.MustRegister(requests, duration, tokens, limited)
	c, err := loadConfig()
	if err != nil {
		slog.Error("config", "err", err)
		os.Exit(1)
	}
	shutdownTracing, err := setupTracing(context.Background())
	if err != nil {
		slog.Error("tracing", "err", err)
		os.Exit(1)
	}
	srv := &http.Server{
		Addr:              c.listen,
		Handler:           newMux(c),
		ReadHeaderTimeout: 5 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(),
		syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		slog.Info("listening", "addr", c.listen, "upstream", c.upstream.String(),
			"tenants", len(c.keys))
		err := srv.ListenAndServe()
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("listen", "err", err)
			os.Exit(1)
		}
	}()
	<-ctx.Done()
	// Graceful Shutdown: laufende Generierungen bis zu 30 s zu Ende bringen
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	slog.Info("shutting down")
	if err := srv.Shutdown(shutdownCtx); err != nil {
		slog.Error("shutdown", "err", err)
	}
	if err := shutdownTracing(shutdownCtx); err != nil { // offene Spans exportieren
		slog.Error("tracing shutdown", "err", err)
	}
}
