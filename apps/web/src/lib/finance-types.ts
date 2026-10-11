export type FinanceFocusTarget = {
  source: "RECURRENCE" | "COMMITMENT" | "CARD_INVOICE";
  id: string;
  credit_card_id: string | null;
  request_id: number;
};
