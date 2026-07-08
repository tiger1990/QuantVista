import { Card, CardContent, CardDescription, CardTitle } from "@/components/ui/card";

export default function RankingsPage() {
  return (
    <Card>
      <CardContent className="space-y-1">
        <CardTitle>Rankings</CardTitle>
        <CardDescription>
          The composite-score leaderboard arrives in the next release (QV-035), backed by the live{" "}
          <code className="font-mono text-xs">/rankings</code> API.
        </CardDescription>
      </CardContent>
    </Card>
  );
}
