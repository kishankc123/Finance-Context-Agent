/**
 * Root React app for the FinContext demo console.
 *
 * The shell mirrors the local React prototype's analyst-console style while
 * staying honest about backend state. Later commits fill each tab with live
 * Agent API data and clearly labeled sample fallbacks.
 */
import { useEffect, useMemo, useState } from "react";
import {
  SAMPLE_BENCHMARK,
  SAMPLE_DRIFT,
  SAMPLE_EVIDENCE,
  SAMPLE_MEMO,
  SAMPLE_PORTFOLIO,
  SAMPLE_RISK,
} from "./data/sampleData.js";
import { AgentApiClient, ApiError } from "./lib/apiClient.js";
import { getRuntimeConfig } from "./lib/config.js";

const TABS = [
  { id: "portfolio", num: "01", label: "Portfolio" },
  { id: "analysis", num: "02", label: "Analysis Run" },
  { id: "drift", num: "03", label: "Disclosure Drift" },
  { id: "evidence", num: "04", label: "Evidence" },
  { id: "risk", num: "05", label: "Risk Scores" },
  { id: "memo", num: "06", label: "Analyst Memo" },
  { id: "benchmark", num: "07", label: "Inference Metrics" },
];

function StatusDot({ tone = "bad", pulse = false }) {
  return <span className={`status-dot ${tone}${pulse ? " pulse" : ""}`} />;
}

function Chip({ children, tone = "muted" }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

function ShellTabPlaceholder({ activeTab }) {
  const tab = TABS.find((item) => item.id === activeTab);
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">React console shell</div>
          <h2>{tab?.label}</h2>
        </div>
        <Chip>Sample shell</Chip>
      </div>
      <div className="empty-state">
        <strong>{tab?.label} content is being wired in the next commits.</strong>
        <span>
          This branch replaces the Gradio fallback with a Vite React console
          that deploys as a HuggingFace Static Space.
        </span>
      </div>
    </section>
  );
}

function PortfolioTab({ portfolio, client, backendOnline }) {
  const [portfolioName, setPortfolioName] = useState(portfolio.name);
  const [file, setFile] = useState(null);
  const ONLINE_STATUS = "Choose a CSV file to upload it to Agent API.";
  const OFFLINE_STATUS = "Agent API is offline. Showing sample portfolio data.";
  const [status, setStatus] = useState(backendOnline ? ONLINE_STATUS : OFFLINE_STATUS);
  useEffect(() => {
    setStatus((prev) =>
      prev === ONLINE_STATUS || prev === OFFLINE_STATUS
        ? backendOnline
          ? ONLINE_STATUS
          : OFFLINE_STATUS
        : prev,
    );
  }, [backendOnline]);
  const [uploadedPortfolioId, setUploadedPortfolioId] = useState("");

  async function uploadPortfolio() {
    if (!file) {
      setStatus("Choose a CSV file before uploading.");
      return;
    }
    try {
      setStatus("Uploading CSV to Agent API...");
      const result = await client.uploadPortfolio(file, portfolioName);
      setUploadedPortfolioId(result.portfolio_id || result.portfolioId || "");
      setStatus("Portfolio uploaded successfully.");
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  return (
    <section className="grid grid-portfolio">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">{portfolio.sourceLabel}</div>
            <h2>Portfolio holdings</h2>
          </div>
          <Chip tone={backendOnline ? "ok" : "warn"}>
            {backendOnline ? "Agent API available" : "Sample preview"}
          </Chip>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Name</th>
                <th>Shares</th>
                <th>Market value</th>
                <th>Weight</th>
                <th>Sector</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.holdings.map((holding) => (
                <tr key={holding.ticker}>
                  <td className="ticker">{holding.ticker}</td>
                  <td>{holding.name}</td>
                  <td>{holding.shares.toLocaleString()}</td>
                  <td>{formatCurrency(holding.marketValue)}</td>
                  <td>{formatPercent(holding.weight)}</td>
                  <td>{holding.sector}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Agent API upload</div>
            <h2>Create portfolio</h2>
          </div>
        </div>
        <div className="panel-body form-stack">
          <label>
            Portfolio name
            <input
              value={portfolioName}
              onChange={(event) => setPortfolioName(event.target.value)}
            />
          </label>
          <label>
            CSV file
            <input
              accept=".csv,text/csv"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </label>
          <button className="primary-button" onClick={uploadPortfolio} type="button">
            Upload to Agent API
          </button>
          <div className="callout">{status}</div>
          {uploadedPortfolioId && (
            <div className="mini-kv">
              <span>portfolio_id</span>
              <strong>{uploadedPortfolioId}</strong>
            </div>
          )}
        </div>
      </aside>
    </section>
  );
}

function AnalysisTab({ client, backendOnline, defaultPortfolioId }) {
  const [portfolioId, setPortfolioId] = useState(defaultPortfolioId);
  const [question, setQuestion] = useState(
    "What changed in supply-chain or customer concentration risk for my semiconductor holdings?",
  );
  const [jobId, setJobId] = useState("");
  const ONLINE_STATUS = "Ready to start an Agent API analysis job.";
  const OFFLINE_STATUS = "Agent API is offline. This tab is ready for live wiring once the API is reachable.";
  const [status, setStatus] = useState(backendOnline ? ONLINE_STATUS : OFFLINE_STATUS);
  useEffect(() => {
    setStatus((prev) =>
      prev === ONLINE_STATUS || prev === OFFLINE_STATUS
        ? backendOnline
          ? ONLINE_STATUS
          : OFFLINE_STATUS
        : prev,
    );
  }, [backendOnline]);
  const [jobPayload, setJobPayload] = useState(null);

  async function startAnalysis() {
    if (!portfolioId.trim()) {
      setStatus("Enter a portfolio_id before starting analysis.");
      return;
    }
    try {
      setStatus("Creating analysis job...");
      const result = await client.startAnalysis({
        portfolioId: portfolioId.trim(),
        question: question.trim() || null,
      });
      const nextJobId = result.job_id || result.jobId || "";
      setJobId(nextJobId);
      setJobPayload(result);
      setStatus(nextJobId ? `Analysis job created: ${nextJobId}` : "Analysis job created.");
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  async function refreshJob() {
    if (!jobId.trim()) {
      setStatus("Enter a job_id before refreshing status.");
      return;
    }
    try {
      setStatus("Refreshing job status...");
      const result = await client.getJob(jobId.trim());
      setJobPayload(result);
      setStatus(result.status ? `Current job status: ${result.status}` : "Job status refreshed.");
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  return (
    <section className="grid grid-analysis">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Analysis request</div>
            <h2>Run disclosure drift analysis</h2>
          </div>
          <Chip tone={backendOnline ? "ok" : "warn"}>
            {backendOnline ? "Live endpoint" : "Offline controls"}
          </Chip>
        </div>
        <div className="panel-body form-stack">
          <label>
            Portfolio ID
            <input value={portfolioId} onChange={(event) => setPortfolioId(event.target.value)} />
          </label>
          <label>
            Research question
            <textarea
              rows="5"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </label>
          <div className="button-row">
            <button className="primary-button" onClick={startAnalysis} type="button">
              Start analysis
            </button>
            <button className="secondary-button" onClick={refreshJob} type="button">
              Refresh job
            </button>
          </div>
          <label>
            Job ID
            <input value={jobId} onChange={(event) => setJobId(event.target.value)} />
          </label>
        </div>
      </div>

      <aside className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Backend response</div>
            <h2>Job status</h2>
          </div>
        </div>
        <div className="panel-body form-stack">
          <div className="callout">{status}</div>
          <pre className="json-block">{JSON.stringify(jobPayload || { status }, null, 2)}</pre>
        </div>
      </aside>
    </section>
  );
}

function DriftTab({ client, backendOnline }) {
  const [ticker, setTicker] = useState("AMD");
  const [section, setSection] = useState("Item 1A");
  const [changes, setChanges] = useState(SAMPLE_DRIFT);
  const ONLINE_STATUS = "Sample drift is visible. Load live diff when Agent API data is ready.";
  const OFFLINE_STATUS = "Agent API is offline. Showing clearly labeled sample disclosure changes.";
  const [status, setStatus] = useState(backendOnline ? ONLINE_STATUS : OFFLINE_STATUS);
  useEffect(() => {
    setStatus((prev) =>
      prev === ONLINE_STATUS || prev === OFFLINE_STATUS
        ? backendOnline
          ? ONLINE_STATUS
          : OFFLINE_STATUS
        : prev,
    );
  }, [backendOnline]);

  async function loadLiveDiff() {
    try {
      setStatus("Loading live disclosure diff from Agent API...");
      const result = await client.getDiff(ticker, { section });
      const nextChanges = normalizeChanges(result);
      setChanges(nextChanges.length ? nextChanges : SAMPLE_DRIFT);
      setStatus(nextChanges.length ? "Live diff loaded." : "No live diff returned; showing sample data.");
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  const visibleChanges = changes.filter((change) => {
    return (!ticker || change.ticker === ticker) && (!section || change.section === section);
  });

  return (
    <section className="grid grid-drift">
      <aside className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Diff controls</div>
            <h2>Disclosure drift</h2>
          </div>
          <Chip tone={backendOnline ? "ok" : "warn"}>
            {backendOnline ? "Can load live" : "Sample data"}
          </Chip>
        </div>
        <div className="panel-body form-stack">
          <label>
            Ticker
            <select value={ticker} onChange={(event) => setTicker(event.target.value)}>
              {["AMD", "NVDA", "MSFT", "JPM", "TSLA"].map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label>
            Filing section
            <select value={section} onChange={(event) => setSection(event.target.value)}>
              {["Item 1", "Item 1A", "Item 7", "Item 7A", "Item 8"].map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <button className="primary-button" onClick={loadLiveDiff} type="button">
            Load diff
          </button>
          <div className="callout">{status}</div>
        </div>
      </aside>

      <div className="drift-stack">
        {visibleChanges.length ? (
          visibleChanges.map((change) => <DriftCard change={change} key={change.id} />)
        ) : (
          <div className="panel empty-state">
            <strong>No sample change for this filter.</strong>
            <span>Try AMD Item 1A or AMD Item 7, or load live Agent API data.</span>
          </div>
        )}
      </div>
    </section>
  );
}

function DriftCard({ change }) {
  return (
    <article className="panel drift-card">
      <div className="panel-head">
        <div>
          <div className="eyebrow">
            {change.ticker} / {change.section} / {humanizeChangeType(change.changeType)}
          </div>
          <h2>{change.topic}</h2>
        </div>
        <div className="badge-row">
          <SeverityBadge severity={change.severity} />
          <Chip>{Math.round(change.confidence * 100)} pct confidence</Chip>
        </div>
      </div>
      <div className="drift-body">
        <p className="summary">{change.summary}</p>
        <div className="comparison-grid">
          <EvidenceQuote label="Prior filing" citation={change.oldCitation} text={change.oldText} />
          <EvidenceQuote label="Current filing" citation={change.newCitation} text={change.newText} />
        </div>
      </div>
    </article>
  );
}

function EvidenceExplorerTab({ client, backendOnline }) {
  const [ticker, setTicker] = useState("AMD");
  const [documents, setDocuments] = useState(SAMPLE_EVIDENCE);
  const ONLINE_STATUS = "Sample evidence is visible. Load live documents when Agent API data is ready.";
  const OFFLINE_STATUS = "Agent API is offline. Showing sample citation-ready chunks.";
  const [status, setStatus] = useState(backendOnline ? ONLINE_STATUS : OFFLINE_STATUS);
  useEffect(() => {
    setStatus((prev) =>
      prev === ONLINE_STATUS || prev === OFFLINE_STATUS
        ? backendOnline
          ? ONLINE_STATUS
          : OFFLINE_STATUS
        : prev,
    );
  }, [backendOnline]);

  async function loadDocuments() {
    try {
      setStatus("Loading indexed documents from Agent API...");
      const result = await client.getDocuments(ticker);
      const nextDocuments = normalizeEvidence(result);
      setDocuments(nextDocuments.length ? nextDocuments : SAMPLE_EVIDENCE);
      setStatus(nextDocuments.length ? "Live documents loaded." : "No live documents returned; showing sample evidence.");
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  const visibleDocuments = documents.filter((item) => !ticker || item.ticker === ticker);

  return (
    <section className="grid grid-evidence">
      <aside className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Evidence controls</div>
            <h2>Indexed chunks</h2>
          </div>
        </div>
        <div className="panel-body form-stack">
          <label>
            Ticker
            <select value={ticker} onChange={(event) => setTicker(event.target.value)}>
              {["AMD", "NVDA", "MSFT", "JPM", "TSLA"].map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <button className="primary-button" onClick={loadDocuments} type="button">
            Load documents
          </button>
          <div className="callout">{status}</div>
        </div>
      </aside>

      <div className="evidence-grid">
        {visibleDocuments.length ? (
          visibleDocuments.map((item) => <EvidenceCard item={item} key={item.chunkId} />)
        ) : (
          <div className="panel empty-state">
            <strong>No evidence chunks for this filter.</strong>
            <span>Load live Agent API data or choose a ticker with sample evidence.</span>
          </div>
        )}
      </div>
    </section>
  );
}

function EvidenceQuote({ label, citation, text }) {
  return (
    <div className="quote-box">
      <div className="eyebrow">{label}</div>
      <CitationChip>{citation}</CitationChip>
      <p>{text}</p>
    </div>
  );
}

function EvidenceCard({ item }) {
  return (
    <article className="panel evidence-card">
      <div className="evidence-card-head">
        <div>
          <div className="eyebrow">
            {item.ticker} / {item.filingType} / {item.section}
          </div>
          <CitationChip>{item.citationAnchor}</CitationChip>
        </div>
        <span className="date-pill">{item.filedAt}</span>
      </div>
      <p>{item.preview}</p>
      <a href={item.sourceUrl} rel="noreferrer" target="_blank">
        Open SEC source
      </a>
    </article>
  );
}

function RiskScoresTab({ client, backendOnline, portfolioId }) {
  const [scores, setScores] = useState(SAMPLE_RISK);
  const ONLINE_STATUS = "Sample risk scores are visible. Load live findings when Agent API data is ready.";
  const OFFLINE_STATUS = "Agent API is offline. Showing sample research risk scores.";
  const [status, setStatus] = useState(backendOnline ? ONLINE_STATUS : OFFLINE_STATUS);
  useEffect(() => {
    setStatus((prev) =>
      prev === ONLINE_STATUS || prev === OFFLINE_STATUS
        ? backendOnline
          ? ONLINE_STATUS
          : OFFLINE_STATUS
        : prev,
    );
  }, [backendOnline]);

  async function loadFindings() {
    try {
      setStatus("Loading findings from Agent API...");
      const result = await client.getFindings(portfolioId);
      const nextScores = normalizeRiskScores(result);
      setScores(nextScores.length ? nextScores : SAMPLE_RISK);
      setStatus(nextScores.length ? "Live risk scores loaded." : "No live scores returned; showing sample scores.");
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  return (
    <section className="grid grid-risk">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Research risk scoring</div>
            <h2>Holding-level risk movement</h2>
          </div>
          <Chip tone={backendOnline ? "ok" : "warn"}>
            {backendOnline ? "Live capable" : "Sample data"}
          </Chip>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Score</th>
                <th>Delta</th>
                <th>Confidence</th>
                <th>Top drivers</th>
                <th>Portfolio impact</th>
              </tr>
            </thead>
            <tbody>
              {scores.map((score) => (
                <tr key={score.ticker}>
                  <td className="ticker">{score.ticker}</td>
                  <td>
                    <ScoreMeter value={score.score} />
                  </td>
                  <td className={score.delta >= 0 ? "delta-up" : "delta-down"}>
                    {score.delta >= 0 ? "+" : ""}
                    {score.delta}
                  </td>
                  <td>{Math.round(score.confidence * 100)} pct</td>
                  <td>{score.drivers.join(", ")}</td>
                  <td>{score.impact}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <aside className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Findings loader</div>
            <h2>Agent API</h2>
          </div>
        </div>
        <div className="panel-body form-stack">
          <button className="primary-button" onClick={loadFindings} type="button">
            Load findings
          </button>
          <div className="callout">{status}</div>
        </div>
      </aside>
    </section>
  );
}

function AnalystMemoTab({ client, backendOnline, portfolioId }) {
  const [memo, setMemo] = useState(SAMPLE_MEMO);
  const ONLINE_STATUS = "Sample memo is visible. Load live findings when Agent API data is ready.";
  const OFFLINE_STATUS = "Agent API is offline. Showing a labeled sample memo structure.";
  const [status, setStatus] = useState(backendOnline ? ONLINE_STATUS : OFFLINE_STATUS);
  useEffect(() => {
    setStatus((prev) =>
      prev === ONLINE_STATUS || prev === OFFLINE_STATUS
        ? backendOnline
          ? ONLINE_STATUS
          : OFFLINE_STATUS
        : prev,
    );
  }, [backendOnline]);

  async function loadMemo() {
    try {
      setStatus("Loading analyst memo from Agent API...");
      const result = await client.getFindings(portfolioId);
      const nextMemo = normalizeMemo(result);
      setMemo(nextMemo || SAMPLE_MEMO);
      setStatus(nextMemo ? "Live memo loaded." : "No live memo returned; showing sample memo.");
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  return (
    <section className="grid grid-memo">
      <article className="panel memo-paper">
        <div className="panel-head">
          <div>
            <div className="eyebrow">{memo.sourceLabel}</div>
            <h2>Analyst memo</h2>
          </div>
          <Chip tone={backendOnline ? "ok" : "warn"}>
            {backendOnline ? "Live capable" : "Sample memo"}
          </Chip>
        </div>
        <div className="memo-body">
          <section>
            <h3>Executive Summary</h3>
            <p>{memo.executiveSummary}</p>
          </section>
          <section>
            <h3>Affected Holdings</h3>
            <div className="pill-row">
              {memo.affectedHoldings.map((holding) => (
                <span className="ticker-pill" key={holding}>
                  {holding}
                </span>
              ))}
            </div>
          </section>
          <section>
            <h3>Watchlist Questions</h3>
            <ol>
              {memo.watchlistQuestions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ol>
          </section>
          <section className="disclaimer-box">
            <h3>Disclaimer</h3>
            <p>{memo.disclaimer}</p>
          </section>
        </div>
      </article>
      <aside className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Memo loader</div>
            <h2>Findings API</h2>
          </div>
        </div>
        <div className="panel-body form-stack">
          <button className="primary-button" onClick={loadMemo} type="button">
            Load memo
          </button>
          <div className="callout">{status}</div>
        </div>
      </aside>
    </section>
  );
}

function BenchmarkTab({ client, backendOnline }) {
  const [benchmark, setBenchmark] = useState(SAMPLE_BENCHMARK);
  const ONLINE_STATUS = "Metric placeholders are visible. Load live NIM/Gateway metrics when Agent API exposes them.";
  const OFFLINE_STATUS = "Agent API is offline. Inference metrics are intentionally unavailable.";
  const [status, setStatus] = useState(backendOnline ? ONLINE_STATUS : OFFLINE_STATUS);
  useEffect(() => {
    setStatus((prev) =>
      prev === ONLINE_STATUS || prev === OFFLINE_STATUS
        ? backendOnline
          ? ONLINE_STATUS
          : OFFLINE_STATUS
        : prev,
    );
  }, [backendOnline]);

  async function loadBenchmark() {
    try {
      setStatus("Loading inference metrics from Agent API...");
      const result = await client.getBenchmarkMetrics();
      const nextBenchmark = normalizeBenchmark(result);
      setBenchmark(nextBenchmark || SAMPLE_BENCHMARK);
      setStatus(nextBenchmark ? "Live inference metrics loaded." : "No live metrics returned; showing unavailable placeholders.");
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  return (
    <section className="grid grid-benchmark">
      <div className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">{benchmark.sourceLabel}</div>
            <h2>Inference metrics panel</h2>
          </div>
          <Chip tone={benchmark.sourceLabel.toLowerCase().includes("sample") ? "warn" : "ok"}>
            {benchmark.sourceLabel}
          </Chip>
        </div>
        <div className="metric-grid">
          {benchmark.metrics.map((metric) => (
            <div className="metric-card" key={metric.label}>
              <div className="eyebrow">{metric.label}</div>
              <strong>{metric.value}</strong>
              <span>{metric.note}</span>
            </div>
          ))}
        </div>
      </div>
      <aside className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Metrics loader</div>
            <h2>Agent API</h2>
          </div>
        </div>
        <div className="panel-body form-stack">
          <button className="primary-button" onClick={loadBenchmark} type="button">
            Load metrics
          </button>
          <div className="callout">{status}</div>
          <div className="mini-kv">
            <span>Truthfulness rule</span>
            <strong>No live number is displayed unless backend returns it.</strong>
          </div>
        </div>
      </aside>
    </section>
  );
}

function ScoreMeter({ value }) {
  return (
    <span className="score-meter">
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      <strong>{value}</strong>
    </span>
  );
}

function CitationChip({ children }) {
  return <span className="citation-chip">{children}</span>;
}

function SeverityBadge({ severity }) {
  return <span className={`severity-badge ${severity}`}>{severity}</span>;
}

export default function App() {
  const [activeTab, setActiveTab] = useState("portfolio");
  const [backend, setBackend] = useState({
    state: "checking",
    label: "Checking backend",
    detail: "Probing Agent API health endpoint.",
  });
  const config = useMemo(() => getRuntimeConfig(), []);
  const client = useMemo(
    () => new AgentApiClient({ baseUrl: config.agentApiUrl }),
    [config.agentApiUrl],
  );
  const backendOnline = backend.state === "online";

  useEffect(() => {
    let cancelled = false;
    client
      .health()
      .then(() => {
        if (!cancelled) {
          setBackend({
            state: "online",
            label: "Backend online",
            detail: `Agent API is reachable at ${config.agentApiUrl}.`,
          });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setBackend({
            state: "offline",
            label: "Backend offline",
            detail:
              error instanceof ApiError
                ? error.message
                : `Agent API is unreachable at ${config.agentApiUrl}.`,
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, config.agentApiUrl]);

  return (
    <div className="app-shell">
      <div className={`backend-banner ${backend.state}`}>
        <StatusDot tone={backendOnline ? "ok" : backend.state === "checking" ? "warn" : "bad"} />
        <span className="mono strong">{backend.label}</span>
        <span>{backend.detail}</span>
      </div>

      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">FC</div>
          <div>
            <div className="brand-name">FinContext Agent</div>
            <div className="brand-sub">SEC Disclosure Drift</div>
          </div>
        </div>

        <button className="command-search" type="button">
          <span>Search filings, tickers, citations</span>
          <kbd>CMD K</kbd>
        </button>

        <div className="topbar-spacer" />

        <div className="top-meta">
          <span className="kv">
            <span className="kv-key">env</span>
            <span className="kv-val">{config.environment}</span>
          </span>
          <span className="kv">
            <StatusDot tone={backendOnline ? "ok" : "bad"} />
            <span className="kv-key">api</span>
            <span className="kv-val">{backendOnline ? "online" : "offline"}</span>
          </span>
        </div>
      </header>

      <nav className="tabbar" aria-label="Demo sections">
        {TABS.map((tab) => (
          <button
            className={`tab ${activeTab === tab.id ? "active" : ""}`}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            type="button"
          >
            <span className="tab-num">{tab.num}</span>
            <span>{tab.label}</span>
          </button>
        ))}
        <div className="tabbar-spacer" />
        <Chip tone="info">React Static Space</Chip>
      </nav>

      <main className="content">
        <section className="hero-row">
          <div>
            <div className="eyebrow">Citation-grounded filing intelligence</div>
            <h1>SEC disclosure drift research console</h1>
            <p>
              Compare filing language changes, inspect citation-ready evidence,
              and keep every memo claim tied to source paragraphs.
            </p>
          </div>
          <aside className="status-card">
            <div className="eyebrow">Backend state</div>
            <strong>{backend.label}</strong>
            <p>{backend.detail}</p>
          </aside>
        </section>

        {activeTab === "portfolio" && (
          <PortfolioTab portfolio={SAMPLE_PORTFOLIO} client={client} backendOnline={backendOnline} />
        )}
        {activeTab === "analysis" && (
          <AnalysisTab
            client={client}
            backendOnline={backendOnline}
            defaultPortfolioId={SAMPLE_PORTFOLIO.id}
          />
        )}
        {activeTab === "drift" && <DriftTab client={client} backendOnline={backendOnline} />}
        {activeTab === "evidence" && (
          <EvidenceExplorerTab client={client} backendOnline={backendOnline} />
        )}
        {activeTab === "risk" && (
          <RiskScoresTab
            client={client}
            backendOnline={backendOnline}
            portfolioId={SAMPLE_PORTFOLIO.id}
          />
        )}
        {activeTab === "memo" && (
          <AnalystMemoTab
            client={client}
            backendOnline={backendOnline}
            portfolioId={SAMPLE_PORTFOLIO.id}
          />
        )}
        {activeTab === "benchmark" && (
          <BenchmarkTab client={client} backendOnline={backendOnline} />
        )}
        {!["portfolio", "analysis", "drift", "evidence", "risk", "memo", "benchmark"].includes(activeTab) && (
          <ShellTabPlaceholder activeTab={activeTab} />
        )}
      </main>
    </div>
  );
}

function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatPercent(value) {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatError(error) {
  return error instanceof Error ? error.message : "Unexpected Agent API error.";
}

function humanizeChangeType(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function normalizeChanges(payload) {
  const records = payload?.changes || payload?.disclosure_changes || payload?.items || [];
  return records.map((item, index) => ({
    id: item.id || item.change_id || `live-change-${index}`,
    ticker: item.ticker || payload?.ticker || "UNKNOWN",
    section: item.section || "Item 1A",
    topic: item.topic || item.summary || "Disclosure change",
    changeType: item.change_type || item.changeType || "new_risk",
    severity: severityFromScore(item.severity),
    confidence: Number(item.confidence ?? 0),
    oldCitation:
      item.old_citation?.citation_anchor || item.old_citation_anchor || item.oldCitation || "Prior citation unavailable",
    newCitation:
      item.new_citation?.citation_anchor || item.new_citation_anchor || item.newCitation || "Current citation unavailable",
    oldText: item.old_text || item.oldText || "Prior filing text unavailable in API response.",
    newText: item.new_text || item.newText || "Current filing text unavailable in API response.",
    summary: item.summary || "Live disclosure change returned by Agent API.",
  }));
}

function normalizeEvidence(payload) {
  const records = payload?.documents || payload?.chunks || payload?.items || [];
  return records.map((item, index) => ({
    chunkId: item.chunk_id || item.document_id || `live-evidence-${index}`,
    ticker: item.ticker || payload?.ticker || "UNKNOWN",
    filingType: item.filing_type || item.filingType || "10-K",
    filedAt: item.filed_at || item.filedAt || "Unknown date",
    section: item.section || "Item 1A",
    citationAnchor: item.citation_anchor || item.citationAnchor || "Citation unavailable",
    sourceUrl: item.source_url || item.sourceUrl || "https://www.sec.gov/",
    preview: item.text || item.preview || item.summary || "No text preview returned by Agent API.",
  }));
}

function severityFromScore(value) {
  if (typeof value === "string") {
    return value.toLowerCase();
  }
  if (value >= 0.75) {
    return "high";
  }
  if (value >= 0.45) {
    return "medium";
  }
  return "low";
}

function normalizeRiskScores(payload) {
  const records = payload?.risk_scores || payload?.riskScores || payload?.scores || [];
  return records.map((item) => ({
    ticker: item.ticker,
    score: Number(item.score ?? item.overall_score ?? 0),
    delta: Number(item.delta ?? item.score_delta ?? 0),
    confidence: Number(item.confidence ?? 0),
    drivers: item.top_drivers || item.drivers || [],
    impact: item.portfolio_impact || item.impact || "Impact not provided by Agent API.",
    citations: item.citations || [],
  }));
}

function normalizeMemo(payload) {
  const memo = payload?.memo || payload?.analyst_memo || null;
  if (!memo) {
    return null;
  }
  return {
    sourceLabel: "Live Agent API memo",
    executiveSummary:
      memo.executive_summary || memo.executiveSummary || "Executive summary unavailable.",
    affectedHoldings: memo.affected_holdings || memo.affectedHoldings || [],
    watchlistQuestions: memo.watchlist_questions || memo.watchlistQuestions || [],
    disclaimer:
      memo.disclaimer ||
      "This output is research assistance only and does not constitute investment advice.",
  };
}

function normalizeBenchmark(payload) {
  const metrics = payload?.metrics || payload;
  if (!metrics || Object.keys(metrics).length === 0) {
    return null;
  }
  const provider = metrics.provider_info || metrics.providerInfo || {};
  const recent = metrics.recent_requests || metrics.recentRequests || {};
  const reasoner = recent["fincontext-reasoner"] || recent.fincontext_reasoner || {};
  const embedding = recent.embedding || {};

  return {
    sourceLabel: provider.provider ? `Live ${provider.provider} metrics` : "Live Agent API metrics",
    status: provider.status || metrics.status || "Live metrics returned by Agent API",
    metrics: [
      {
        label: "Reasoner tokens/sec",
        value: valueOrUnavailable(
          reasoner.avg_tokens_per_second ?? reasoner.avgTokensPerSecond ?? metrics.tokens_per_second ?? metrics.tokensPerSecond,
        ),
        note: "Reported by backend metrics endpoint",
      },
      {
        label: "Time to first token",
        value: valueOrUnavailable(
          reasoner.avg_time_to_first_token_ms ?? reasoner.avgTimeToFirstTokenMs ?? metrics.time_to_first_token_ms ?? metrics.timeToFirstTokenMs,
          " ms",
        ),
        note: "Reported by backend metrics endpoint",
      },
      {
        label: "Provider status",
        value: valueOrUnavailable(provider.status ?? metrics.provider_status ?? metrics.providerStatus),
        note: "Reported by backend metrics endpoint",
      },
      {
        label: "Embedding latency",
        value: valueOrUnavailable(
          embedding.avg_latency_ms ?? embedding.avgLatencyMs ?? metrics.embedding_latency_ms ?? metrics.embeddingLatencyMs,
          " ms",
        ),
        note: "Reported by backend metrics endpoint",
      },
    ],
  };
}

function valueOrUnavailable(value, suffix = "") {
  return value === undefined || value === null || value === ""
    ? "Unavailable"
    : `${value}${suffix}`;
}
