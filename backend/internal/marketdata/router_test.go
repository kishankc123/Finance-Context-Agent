package marketdata

import "testing"

func TestNeedsLiveMarketData(t *testing.T) {
	cases := map[string]bool{
		"What is AMD's current stock price?":                    true,
		"What is NVDA's market cap right now?":                  true,
		"How did AMD's Item 1A risk language change year over year?": false,
		"Compare export control disclosures between AMD and NVDA":    false,
	}
	for question, want := range cases {
		if got := NeedsLiveMarketData(question); got != want {
			t.Errorf("NeedsLiveMarketData(%q) = %v, want %v", question, got, want)
		}
	}
}
