package marketdata

import "strings"

// liveDataKeywords are terms that signal the question is about the current
// market state rather than filing language. This is a minimal heuristic,
// not an intent classifier — good enough to decide fixture-retrieval vs.
// live-tool-call routing until the agent loop does real planning.
var liveDataKeywords = []string{
	"current price", "stock price", "share price", "trading at",
	"market cap", "p/e", "pe ratio", "eps", "valuation today",
	"today's", "right now", "live price", "quote",
}

// NeedsLiveMarketData reports whether a question should be routed to the
// market-data-tool-server instead of (or in addition to) filing retrieval.
func NeedsLiveMarketData(question string) bool {
	lower := strings.ToLower(question)
	for _, kw := range liveDataKeywords {
		if strings.Contains(lower, kw) {
			return true
		}
	}
	return false
}
