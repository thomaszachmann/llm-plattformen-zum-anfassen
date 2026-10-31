//go:build pprof

package main

import (
	"log/slog"
	"net/http"
	_ "net/http/pprof" // registriert /debug/pprof/* am DefaultServeMux
)

// Nur mit "go build -tags pprof": Profiling auf eigenem, lokalem Port.
// Das Gateway nutzt eine eigene ServeMux, /debug/pprof ist dort nicht erreichbar.
func init() {
	go func() {
		slog.Info("pprof", "addr", "127.0.0.1:6060")
		err := http.ListenAndServe("127.0.0.1:6060", nil)
		slog.Error("pprof", "err", err)
	}()
}
