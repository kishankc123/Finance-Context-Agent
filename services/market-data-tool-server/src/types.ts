export interface StockQuote {
  ticker: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number | null;
  asOf: string;
}

export interface CompanyFundamentals {
  ticker: string;
  marketCap: number | null;
  peRatio: number | null;
  eps: number | null;
  sector: string | null;
  asOf: string;
}

export class MarketDataError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "MarketDataError";
    this.status = status;
    this.code = code;
  }
}
