import { Card, CardContent, CardDescription, CardTitle } from "@/components/ui/card";

export default function StocksPage() {
  return (
    <Card>
      <CardContent className="space-y-1">
        <CardTitle>Stocks</CardTitle>
        <CardDescription>
          The filterable, sortable universe list arrives in the next release (QV-035), backed by the
          live <code className="font-mono text-xs">/stocks</code> API.
        </CardDescription>
      </CardContent>
    </Card>
  );
}
