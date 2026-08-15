// Package marketdata is a thin HTTP client for the market-data-tool-server
// Node service (services/market-data-tool-server). It is the only place in
// the Go codebase that knows that service's URL and response shapes.
package marketdata

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// DefaultTimeout is the recommended per-call timeout for callers of Client.
const DefaultTimeout = 5 * time.Second

type Quote struct {
	Ticker        string  `json:"ticker"`
	Price         float64 `json:"price"`
	Change        float64 `json:"change"`
	ChangePercent float64 `json:"changePercent"`
	Volume        *int64  `json:"volume"`
	AsOf          string  `json:"asOf"`
	Cached        bool    `json:"cached"`
}

type Fundamentals struct {
	Ticker    string   `json:"ticker"`
	MarketCap *float64 `json:"marketCap"`
	PERatio   *float64 `json:"peRatio"`
	EPS       *float64 `json:"eps"`
	Sector    *string  `json:"sector"`
	AsOf      string   `json:"asOf"`
	Cached    bool     `json:"cached"`
}

type ToolSchema struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	Endpoint    struct {
		Method string `json:"method"`
		Path   string `json:"path"`
	} `json:"endpoint"`
	Parameters json.RawMessage `json:"parameters"`
}

type apiError struct {
	Error struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

type Client struct {
	baseURL    string
	httpClient *http.Client
}

func NewClient(baseURL string) *Client {
	return &Client{
		baseURL:    baseURL,
		httpClient: &http.Client{Timeout: 5 * time.Second},
	}
}

func (c *Client) GetQuote(ctx context.Context, ticker string) (Quote, error) {
	var q Quote
	err := c.get(ctx, "/tools/get_stock_quote", ticker, &q)
	return q, err
}

func (c *Client) GetFundamentals(ctx context.Context, ticker string) (Fundamentals, error) {
	var f Fundamentals
	err := c.get(ctx, "/tools/get_company_fundamentals", ticker, &f)
	return f, err
}

// FetchToolSchemas is called once at Agent API startup to register the
// Node service's tool definitions rather than hardcoding them in Go.
func (c *Client) FetchToolSchemas(ctx context.Context) ([]ToolSchema, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/tools/schema", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("marketdata: fetch tool schemas: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("marketdata: fetch tool schemas: unexpected status %d", resp.StatusCode)
	}

	var body struct {
		Tools []ToolSchema `json:"tools"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, fmt.Errorf("marketdata: decode tool schemas: %w", err)
	}
	return body.Tools, nil
}

func (c *Client) get(ctx context.Context, path, ticker string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return err
	}
	q := req.URL.Query()
	q.Set("ticker", ticker)
	req.URL.RawQuery = q.Encode()

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("marketdata: request %s: %w", path, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		var apiErr apiError
		_ = json.NewDecoder(resp.Body).Decode(&apiErr)
		if apiErr.Error.Message != "" {
			return fmt.Errorf("marketdata: %s (%s)", apiErr.Error.Message, apiErr.Error.Code)
		}
		return fmt.Errorf("marketdata: %s returned status %d", path, resp.StatusCode)
	}

	return json.NewDecoder(resp.Body).Decode(out)
}
