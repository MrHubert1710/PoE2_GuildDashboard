export const balanceColors=['#a7d9b2','#8ebce7','#edaa92','#d6b1ee','#e7d28e','#85d3cf','#f2a4cb','#a8b6e8']

export function balanceColor(series:{aggregate?:boolean;color?:string},index:number){return series.color??(series.aggregate?'#e1e7ee':balanceColors[index%balanceColors.length])}
