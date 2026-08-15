package provider

import (
	"context"
	"fmt"
	"log/slog"
	"strings"

	"fincontext/backend/internal/citations"
	"fincontext/backend/internal/data"
	"fincontext/backend/internal/domain"
	"fincontext/backend/internal/marketdata"
)

type ChatProvider interface {
	Answer(question string) (domain.ChatAnswer, error)
}

type FixtureProvider struct {
	store      *data.Store
	validator  citations.Validator
	marketData *marketdata.Client
}

func NewFixtureProvider(store *data.Store, validator citations.Validator) FixtureProvider {
	return FixtureProvider{store: store, validator: validator}
}

// WithMarketData enables live-price/valuation routing for questions that
// need current market data rather than filing evidence. Passing nil (the
// zero value) keeps the fixture-only behavior, so existing callers are
// unaffected.
func (p FixtureProvider) WithMarketData(client *marketdata.Client) FixtureProvider {
	p.marketData = client
	return p
}

func (p FixtureProvider) Answer(question string) (domain.ChatAnswer, error) {
	ids := []string{"amd_2025_supply_chain", "amd_2025_export_controls"}
	text := "AMD's supply-chain risk reads higher because the newer disclosure is more specific about dependence on third-party manufacturers for advanced process nodes. The same evidence set also adds export-control exposure for AI accelerators, so the portfolio impact is concentrated in the semiconductor sleeve."
	if strings.Contains(strings.ToLower(question), "customer") {
		ids = append(ids, "nvda_2025_customer_concentration")
		text += " NVDA adds a related customer-concentration signal, which makes the semiconductor comparison useful rather than AMD-only."
	}
	cites, err := p.validator.Citations(ids)
	if err != nil {
		return domain.ChatAnswer{}, err
	}

	if p.marketData != nil {
		if extra := p.liveMarketDataAddendum(question); extra != "" {
			text += extra
		}
	}

	return domain.ChatAnswer{
		Answer:     text,
		Citations:  cites,
		Disclaimer: domain.ResearchDisclaimer,
	}, nil
}

// liveMarketDataAddendum routes to the market-data-tool-server when the
// question needs current price/valuation data instead of (or alongside)
// filing evidence. It never fails the whole answer: if the tool call
// errors, we log and fall back to filing-only content, since every
// factual claim in the memo must still trace to a validated citation.
func (p FixtureProvider) liveMarketDataAddendum(question string) string {
	if !marketdata.NeedsLiveMarketData(question) {
		return ""
	}

	ticker := ""
	lower := strings.ToLower(question)
	switch {
	case strings.Contains(lower, "nvda") || strings.Contains(lower, "nvidia"):
		ticker = "NVDA"
	case strings.Contains(lower, "amd"):
		ticker = "AMD"
	default:
		return ""
	}

	ctx, cancel := context.WithTimeout(context.Background(), marketdata.DefaultTimeout)
	defer cancel()

	quote, err := p.marketData.GetQuote(ctx, ticker)
	if err != nil {
		slog.Warn("market data tool call failed", "ticker", ticker, "error", err)
		return ""
	}

	return fmt.Sprintf(
		" As of %s, %s is trading at $%.2f (%.2f%% on the day) — this is live market data, not a filing citation, and is not investment advice.",
		quote.AsOf, ticker, quote.Price, quote.ChangePercent,
	)
}
