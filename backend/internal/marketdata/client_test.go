package marketdata

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestGetQuote(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/tools/get_stock_quote" || r.URL.Query().Get("ticker") != "AMD" {
			t.Fatalf("unexpected request: %s %s", r.Method, r.URL.String())
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"ticker":"AMD","price":172.5,"change":1.25,"changePercent":0.73,"volume":5000000,"asOf":"2026-08-13T00:00:00.000Z","cached":false}`))
	}))
	defer server.Close()

	client := NewClient(server.URL)
	quote, err := client.GetQuote(context.Background(), "AMD")
	if err != nil {
		t.Fatalf("GetQuote returned error: %v", err)
	}
	if quote.Price != 172.5 || quote.Ticker != "AMD" {
		t.Errorf("unexpected quote: %+v", quote)
	}
}

func TestGetQuoteUpstreamError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte(`{"error":{"code":"UNKNOWN_TICKER","message":"No quote data found for 'ZZZZZZ'"}}`))
	}))
	defer server.Close()

	client := NewClient(server.URL)
	_, err := client.GetQuote(context.Background(), "ZZZZZZ")
	if err == nil {
		t.Fatal("expected error for unknown ticker, got nil")
	}
}
