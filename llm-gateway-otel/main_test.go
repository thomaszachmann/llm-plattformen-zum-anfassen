package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

// fakeModel spielt einen OpenAI-kompatiblen Modellserver.
func fakeModel(t *testing.T) *httptest.Server {
	h := func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "" {
			t.Error("Authorization darf nicht zum Upstream durchgereicht werden")
		}
		if r.Header.Get("X-Tenant") == "" && r.URL.Path != "/v1/models" {
			t.Error("X-Tenant fehlt")
		}
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"choices":[{"message":{"content":"hi"}}],`+
			`"usage":{"prompt_tokens":7,"completion_tokens":3}}`)
	}
	return httptest.NewServer(http.HandlerFunc(h))
}

func testConfig(up string, rps float64, burst int) config {
	u, _ := url.Parse(up)
	keys := map[string]string{"k-acme": "acme"}
	return config{upstream: u, keys: keys, rps: rps, burst: burst}
}

func post(h http.Handler, key string) *httptest.ResponseRecorder {
	body := strings.NewReader(`{}`)
	req := httptest.NewRequest("POST", "/v1/chat/completions", body)
	req.Header.Set("Authorization", "Bearer "+key)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestLoadConfig(t *testing.T) {
	type kv = map[string]string
	tests := []struct {
		name    string
		env     kv
		wantErr bool
	}{
		{"ok", kv{"TENANT_KEYS": "acme:k1,globex:k2"}, false},
		{"keine Keys", kv{}, true},
		{"kaputtes Paar", kv{"TENANT_KEYS": "acme"}, true},
		{"rps null", kv{"TENANT_KEYS": "a:k", "RATE_LIMIT_RPS": "0"}, true},
		{"burst text", kv{"TENANT_KEYS": "a:k", "RATE_LIMIT_BURST": "x"}, true},
		{"ohne host", kv{"TENANT_KEYS": "a:k", "UPSTREAM_URL": "ollama:11434"}, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			for _, k := range []string{"TENANT_KEYS", "RATE_LIMIT_RPS",
				"RATE_LIMIT_BURST", "UPSTREAM_URL"} {
				t.Setenv(k, tt.env[k]) // leer = Default
			}
			_, err := loadConfig()
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestUnknownKey(t *testing.T) {
	up := fakeModel(t)
	defer up.Close()
	rec := post(newMux(testConfig(up.URL, 5, 5)), "falsch")
	if rec.Code != 401 {
		t.Fatalf("Status = %d, erwartet 401", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("Content-Type = %q, erwartet application/json", ct)
	}
}

func TestProxyCountsTokens(t *testing.T) {
	up := fakeModel(t)
	defer up.Close()
	completion := tokens.WithLabelValues("acme", "completion")
	before := testutil.ToFloat64(completion)
	if got := post(newMux(testConfig(up.URL, 5, 5)), "k-acme").Code; got != 200 {
		t.Fatalf("Status = %d, erwartet 200", got)
	}
	if d := testutil.ToFloat64(completion) - before; d != 3 {
		t.Fatalf("completion tokens = %v, erwartet 3", d)
	}
}

func TestRateLimit(t *testing.T) {
	up := fakeModel(t)
	defer up.Close()
	h := newMux(testConfig(up.URL, 1, 2))
	codes := []int{post(h, "k-acme").Code, post(h, "k-acme").Code,
		post(h, "k-acme").Code}
	if codes[2] != 429 {
		t.Fatalf("Codes = %v, dritte Anfrage sollte 429 sein", codes)
	}
}

// TestConcurrentTenants ist für "go test -race" da: viele Mandanten gleichzeitig.
func TestConcurrentTenants(t *testing.T) {
	up := fakeModel(t)
	defer up.Close()
	c := testConfig(up.URL, 100, 100)
	c.keys = map[string]string{"k-a": "a", "k-b": "b", "k-c": "c", "k-d": "d"}
	h := newMux(c)
	var wg sync.WaitGroup
	for i := range 40 {
		wg.Go(func() { post(h, []string{"k-a", "k-b", "k-c", "k-d"}[i%4]) })
	}
	wg.Wait()
}

func TestReadyz(t *testing.T) {
	up := fakeModel(t)
	h := newMux(testConfig(up.URL, 5, 5))
	get := func() int {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("GET", "/readyz", nil))
		return rec.Code
	}
	if got := get(); got != 200 {
		t.Fatalf("readyz = %d, erwartet 200", got)
	}
	up.Close() // Modellserver weg -> nicht mehr ready
	if got := get(); got != 503 {
		t.Fatalf("readyz = %d, erwartet 503", got)
	}
}

// TestTracing prüft Server- und Client-Span sowie traceparent zum Upstream.
func TestTracing(t *testing.T) {
	sr := tracetest.NewSpanRecorder()
	otel.SetTracerProvider(sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(sr)))
	otel.SetTextMapPropagator(propagation.TraceContext{})
	var parent string
	h := func(w http.ResponseWriter, r *http.Request) {
		parent = r.Header.Get("Traceparent")
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"usage":{"prompt_tokens":7,"completion_tokens":3}}`)
	}
	up := httptest.NewServer(http.HandlerFunc(h))
	defer up.Close()
	if got := post(newMux(testConfig(up.URL, 5, 5)), "k-acme").Code; got != 200 {
		t.Fatalf("Status = %d, erwartet 200", got)
	}
	spans := sr.Ended()
	if len(spans) != 2 {
		t.Fatalf("%d Spans, erwartet 2 (Server + Client)", len(spans))
	}
	tid := spans[0].SpanContext().TraceID()
	if spans[1].SpanContext().TraceID() != tid {
		t.Fatal("Server- und Client-Span gehören nicht zum selben Trace")
	}
	if !strings.Contains(parent, tid.String()) {
		t.Fatalf("traceparent %q enthält Trace-ID %s nicht", parent, tid)
	}
	var out int64
	for _, s := range spans {
		for _, a := range s.Attributes() {
			if a.Key == "gen_ai.usage.output_tokens" {
				out = a.Value.AsInt64()
			}
		}
	}
	if out != 3 {
		t.Fatalf("gen_ai.usage.output_tokens = %d, erwartet 3", out)
	}
}
