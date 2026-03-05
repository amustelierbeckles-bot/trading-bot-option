import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Area, AreaChart } from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function BacktestChart({ result }) {
  if (!result || !result.trades || result.trades.length === 0) {
    return null;
  }

  // Build capital evolution data
  let runningCapital = result.initial_capital;
  const capitalData = [{ trade: 0, capital: runningCapital, label: 'Inicio' }];

  result.trades.forEach((trade, idx) => {
    runningCapital += trade.profit_loss;
    capitalData.push({
      trade: idx + 1,
      capital: parseFloat(runningCapital.toFixed(2)),
      label: `Trade ${idx + 1}`,
      profit_loss: trade.profit_loss
    });
  });

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-black/90 backdrop-blur-md border border-white/10 p-3 rounded-lg">
          <p className="font-mono text-xs text-muted-foreground mb-1">{data.label}</p>
          <p className="font-mono text-sm font-bold text-foreground">Capital: ${data.capital.toLocaleString()}</p>
          {data.profit_loss !== undefined && (
            <p className={`font-mono text-xs mt-1 ${data.profit_loss >= 0 ? 'text-buy' : 'text-sell'}`}>
              P&L: {data.profit_loss >= 0 ? '+' : ''}${data.profit_loss.toFixed(2)}
            </p>
          )}
        </div>
      );
    }
    return null;
  };

  return (
    <Card className="bg-[#080808] border-white/5 mb-6" data-testid="capital-evolution-chart">
      <CardHeader>
        <CardTitle className="text-xl font-heading font-bold text-foreground">Evolución del Capital</CardTitle>
        <CardDescription className="font-mono text-xs">Capital a lo largo de las operaciones</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={350}>
          <AreaChart data={capitalData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="capitalGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#2962FF" stopOpacity={0.8}/>
                <stop offset="95%" stopColor="#2962FF" stopOpacity={0.1}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272A" />
            <XAxis 
              dataKey="trade" 
              stroke="#52525B" 
              style={{ fontSize: '11px', fontFamily: 'JetBrains Mono' }}
              tick={{ fill: '#A1A1AA' }}
              label={{ value: 'Número de Operación', position: 'insideBottom', offset: -5, style: { fill: '#A1A1AA', fontSize: '11px' } }}
            />
            <YAxis 
              stroke="#52525B" 
              style={{ fontSize: '11px', fontFamily: 'JetBrains Mono' }}
              tick={{ fill: '#A1A1AA' }}
              label={{ value: 'Capital ($)', angle: -90, position: 'insideLeft', style: { fill: '#A1A1AA', fontSize: '11px' } }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area 
              type="monotone" 
              dataKey="capital" 
              stroke="#2962FF" 
              strokeWidth={3}
              fill="url(#capitalGradient)"
              name="Capital"
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}