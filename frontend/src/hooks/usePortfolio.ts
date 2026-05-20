import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { usePeriod } from "../components/PeriodContext";

export function usePortfolio(account: string = "all") {
  const { period } = usePeriod();
  return useQuery({
    queryKey: ["portfolio", account, period],
    queryFn: () => api.portfolio(account, period),
  });
}

export function useCorrelation(account: string = "all") {
  const { period } = usePeriod();
  return useQuery({
    queryKey: ["correlation", account, period],
    queryFn: () => api.correlation(account, period),
  });
}

export function useHistory(ticker: string | null) {
  return useQuery({
    queryKey: ["history", ticker],
    queryFn: () => api.history(ticker!),
    enabled: !!ticker,
  });
}
