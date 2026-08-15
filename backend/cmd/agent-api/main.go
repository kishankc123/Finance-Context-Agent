package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"time"

	"fincontext/backend/internal/agent"
	"fincontext/backend/internal/citations"
	"fincontext/backend/internal/config"
	"fincontext/backend/internal/data"
	"fincontext/backend/internal/gatewayclient"
	"fincontext/backend/internal/httpapi"
	"fincontext/backend/internal/marketdata"
	"fincontext/backend/internal/provider"
	"fincontext/backend/internal/sqlstore"
	"fincontext/backend/internal/vector"
)

type gatewayHealth struct {
	client gatewayclient.Client
}

func (g gatewayHealth) Health(ctx context.Context) error {
	return g.client.Check(ctx)
}

func main() {
	cfg := config.LoadAgentAPI()
	store, err := data.Load(cfg.FixtureDir)
	if err != nil {
		slog.Error("load fixtures", "error", err)
		os.Exit(1)
	}

	sqlite, err := sqlstore.Open(cfg.SQLitePath)
	if err != nil {
		slog.Error("open sqlite", "path", cfg.SQLitePath, "error", err)
		os.Exit(1)
	}
	defer sqlite.Close()
	if err := sqlite.SeedFixtures(context.Background(), store.Portfolio, store.Evidence); err != nil {
		slog.Error("seed sqlite fixtures", "error", err)
		os.Exit(1)
	}

	qdrant := vector.NewQdrantClient(cfg.QdrantURL)
	if err := qdrant.EnsureCollection(context.Background(), cfg.QdrantCollection, cfg.VectorSize); err != nil {
		if cfg.StrictDeps {
			slog.Error("ensure qdrant collection", "error", err)
			os.Exit(1)
		}
		slog.Warn("qdrant unavailable; continuing in degraded mode", "error", err)
	}

	validator := citations.NewValidator(store)
	runner := agent.NewRunner(store, validator, sqlite)
	marketDataClient := marketdata.NewClient(cfg.MarketDataURL)
	chatProvider := provider.NewFixtureProvider(store, validator).WithMarketData(marketDataClient)
	gateway := gatewayclient.New(cfg.GatewayURL)
	server := httpapi.New(store, runner, chatProvider, cfg.StaticDir, httpapi.Dependencies{
		SQLite:  sqlite,
		Qdrant:  qdrant,
		Gateway: gatewayHealth{client: gateway},
	})

	httpServer := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           server,
		ReadHeaderTimeout: 5 * time.Second,
	}

	slog.Info("starting agent api", "port", cfg.Port, "sqlite", cfg.SQLitePath, "qdrant", cfg.QdrantURL, "gateway", cfg.GatewayURL)
	if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("agent api stopped", "error", err)
		os.Exit(1)
	}
}
