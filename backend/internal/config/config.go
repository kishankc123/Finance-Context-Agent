package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type AgentAPI struct {
	Port             string
	FixtureDir       string
	StaticDir        string
	SQLitePath       string
	QdrantURL        string
	QdrantCollection string
	GatewayURL       string
	MarketDataURL    string
	VectorSize       int
	StrictDeps       bool
}

type Gateway struct {
	Port             string
	NIMBaseURL       string
	NIMAPIKey        string
	NIMPlannerModel  string
	NIMReasonerModel string
	EmbeddingURL     string
	RerankerURL      string
	Timeout          time.Duration
}

func LoadAgentAPI() AgentAPI {
	return AgentAPI{
		Port:             env("PORT", "8090"),
		FixtureDir:       env("FIXTURE_DIR", "data/fixtures"),
		StaticDir:        os.Getenv("STATIC_DIR"),
		SQLitePath:       env("SQLITE_DB_PATH", "fincontext.db"),
		QdrantURL:        env("QDRANT_URL", "http://localhost:6333"),
		QdrantCollection: env("QDRANT_COLLECTION", "fincontext_chunks"),
		GatewayURL:       env("INFERENCE_GATEWAY_URL", "http://localhost:8080"),
		MarketDataURL:    env("MARKET_DATA_URL", "http://localhost:8091"),
		VectorSize:       intEnv("QDRANT_VECTOR_SIZE", 1024),
		StrictDeps:       boolEnv("STRICT_DEPENDENCIES", false),
	}
}

func LoadGateway() Gateway {
	return Gateway{
		Port:             env("PORT", "8080"),
		NIMBaseURL:       env("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
		NIMAPIKey:        os.Getenv("NIM_API_KEY"),
		NIMPlannerModel:  env("NIM_PLANNER_MODEL", "Qwen/Qwen2.5-14B-Instruct"),
		NIMReasonerModel: env("NIM_REASONER_MODEL", "Qwen/Qwen2.5-72B-Instruct"),
		EmbeddingURL:     os.Getenv("EMBEDDING_URL"),
		RerankerURL:      os.Getenv("RERANKER_URL"),
		Timeout:          time.Duration(intEnv("UPSTREAM_TIMEOUT_SECONDS", 60)) * time.Second,
	}
}

func env(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

func intEnv(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func boolEnv(key string, fallback bool) bool {
	value := strings.ToLower(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value == "1" || value == "true" || value == "yes"
}
