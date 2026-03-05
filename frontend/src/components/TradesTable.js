import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, CheckCircle, XCircle } from "lucide-react";

export default function TradesTable({ trades }) {
  if (!trades || trades.length === 0) {
    return null;
  }

  return (
    <Card className="bg-card border-border" data-testid="trades-table">
      <CardHeader>
        <CardTitle className="text-xl font-heading font-bold text-foreground">Operaciones Recientes</CardTitle>
        <CardDescription className="font-mono text-xs">Últimas {trades.length} operaciones simuladas</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-3 px-4 font-mono text-xs text-muted-foreground uppercase">#</th>
                <th className="text-left py-3 px-4 font-mono text-xs text-muted-foreground uppercase">Tipo</th>
                <th className="text-left py-3 px-4 font-mono text-xs text-muted-foreground uppercase">Precio Entrada</th>
                <th className="text-left py-3 px-4 font-mono text-xs text-muted-foreground uppercase">Precio Salida</th>
                <th className="text-right py-3 px-4 font-mono text-xs text-muted-foreground uppercase">P&L</th>
                <th className="text-center py-3 px-4 font-mono text-xs text-muted-foreground uppercase">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade, idx) => {
                const isProfit = trade.win || trade.profit_loss > 0;
                const isCall = trade.type === 'CALL' || trade.type === 'BUY';
                const Icon = isCall ? TrendingUp : TrendingDown;
                
                return (
                  <tr key={idx} className="border-b border-border/50 hover:bg-muted/30 transition-colors" data-testid={`trade-row-${idx}`}>
                    <td className="py-3 px-4 font-mono text-xs text-muted-foreground">{idx + 1}</td>
                    <td className="py-3 px-4">
                      <Badge 
                        variant="outline" 
                        className={`font-mono text-xs ${
                          isCall
                            ? 'bg-buy/10 text-buy border-buy/20'
                            : 'bg-sell/10 text-sell border-sell/20'
                        }`}
                      >
                        <Icon className="w-3 h-3 mr-1" />
                        {trade.type}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 font-mono text-sm text-foreground">
                      ${trade.entry_price?.toFixed ? trade.entry_price.toFixed(5) : trade.entry_price}
                    </td>
                    <td className="py-3 px-4 font-mono text-sm text-foreground">
                      ${trade.exit_price?.toFixed ? trade.exit_price.toFixed(5) : trade.exit_price}
                    </td>
                    <td className={`py-3 px-4 font-mono text-sm font-bold text-right ${
                      isProfit ? 'text-buy' : 'text-sell'
                    }`}>
                      {isProfit ? '+' : ''}${trade.profit_loss?.toFixed ? trade.profit_loss.toFixed(2) : trade.profit_loss}
                    </td>
                    <td className="py-3 px-4 text-center">
                      {isProfit ? (
                        <CheckCircle className="w-5 h-5 text-buy inline" />
                      ) : (
                        <XCircle className="w-5 h-5 text-sell inline" />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
