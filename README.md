# 🌤 Tempo-Bet — Bot de Apostas Meteorológicas para Polymarket

Bot automatizado para negociar mercados meteorológicos no Polymarket. Encontra preços errados de temperaturas usando dados reais de previsão de múltiplas fontes em 20 cidades pelo mundo.

Sem SDK. Sem caixa preta. Python puro.

---

## Como Funciona

O Polymarket cria mercados como "A temperatura mais alta em São Paulo será entre 30-31°C no dia 15 de março?". Esses mercados frequentemente estão com preços errados — a previsão diz 78% de chance mas o mercado está negociando a 8 centavos.

O bot:
1. Busca previsões de ECMWF e HRRR via Open-Meteo (gratuito, sem chave)
2. Obtém observações em tempo real via METAR (aeroportos)
3. Encontra o bucket de temperatura correspondente no Polymarket
4. Calcula o Valor Esperado (EV) — só entra se a matemática for positiva
5. Dimensiona a posição usando o Kelly Criterion fracionado
6. Monitora stops a cada 10 min, scan completo a cada hora
7. Auto-resolve mercados consultando a API do Polymarket

---

## Por que Coordenadas de Aeroporto Importam

A maioria dos bots usa coordenadas do centro da cidade. Isso está errado.

Cada mercado do Polymarket resolve baseado em uma estação específica de aeroporto. São Paulo resolve no Aeroporto de Guarulhos (SBSP), não no centro da cidade. A diferença entre centro e aeroporto pode ser 3-8°C. Em mercados com buckets de 1-2°C, isso é a diferença entre o trade certo e uma perda garantida.

| Cidade | Estação | Aeroporto |
|--------|---------|-----------|
| São Paulo | SBSP | Guarulhos |
| Buenos Aires | SAEZ | Ezeiza |
| Nova York | KLGA | LaGuardia |
| Chicago | KORD | O'Hare |
| Londres | EGLC | London City |
| Tóquio | RJTT | Haneda |

---

## Cidades Suportadas (20)

### Estados Unidos (6)
- Nova York (KLGA)
- Chicago (KORD)
- Miami (KMIA)
- Dallas (KDAL)
- Seattle (KSEA)
- Atlanta (KATL)

### Europa (4)
- Londres (EGLC)
- Paris (LFPG)
- Munique (EDDM)
- Ancara (LTAC)

### Ásia (6)
- Seul (RKSI)
- Tóquio (RJTT)
- Xangai (ZSPD)
- Singapura (WSSS)
- Lucknow (VILK)
- Tel Aviv (LLBG)

### América do Sul (2)
- São Paulo (SBSP)
- Buenos Aires (SAEZ)

### Canadá (1)
- Toronto (CYYZ)

### Oceania (1)
- Wellington (NZWN)

---

## APIs Usadas

| API | Autenticação | Propósito |
|-----|--------------|-----------|
| Open-Meteo | Nenhuma | Previsões ECMWF + HRRR |
| Aviation Weather (METAR) | Nenhuma | Observações em tempo real |
| Polymarket Gamma | Nenhuma | Dados dos mercados |
| Visual Crossing | Chave gratuita | Temperaturas históricas para resolução |

---

## Instalação

```bash
cd ~/Projects/Tempo-bet
pip install requests
```

---

## Configuração

Edite `config.json`:

```json
{
  "balance": 10000.0,        // Saldo inicial em USDC
  "max_bet": 20.0,           // Aposta máxima por trade
  "min_ev": 0.05,           // Valor Esperado mínimo (5%)
  "max_price": 0.45,        // Preço máximo para entrar (< 45 cents)
  "min_volume": 2000,        // Volume mínimo do mercado
  "min_hours": 2.0,         // Horas mínimas até resolução
  "max_hours": 72.0,        // Horas máximas até resolução
  "kelly_fraction": 0.25,   // Fração do Kelly (25%)
  "max_slippage": 0.03,     // Spread máximo permitido
  "scan_interval": 3600,     // Intervalo de scan (1 hora)
  "calibration_min": 30,     // Mínimo de markets para calibrar
  "vc_key": "SUA_CHAVE_VC"  // Chave Visual Crossing (grátis)
}
```

### Obtendo a Chave Visual Crossing

1. Acesse [visualcrossing.com](https://www.visualcrossing.com)
2. Crie uma conta gratuita
3. Gere uma API key gratuita
4. Cole no `config.json`

---

## Uso

```bash
# Iniciar o bot (scans a cada hora)
python bot_v2.py run

# Ver saldo e posições abertas
python bot_v2.py status

# Relatório completo de todos os mercados resolvidos
python bot_v2.py report
```

---

## Estratégia de Trading

### Valor Esperado (EV)
```
EV = (probabilidade × retorno) - custo
```
Só entra se EV > 0.05 (5%)

### Kelly Criterion
```
f* = (p × b - q) / b
```
Onde:
- p = probabilidade de ganhar
- q = 1 - p
- b = odds (1/price - 1)

Usa 25% do Kelly para reduzir variância.

### Gerenciamento de Risco
- **Stop-loss**: 20% do valor apostado
- **Trailing stop**: Move para breakeven quando lucra +20%
- **Filtro de slippage**: Ignora mercados com spread > $0.03

---

## Armazenamento de Dados

Todos os dados são salvos em `data/markets/` — um arquivo JSON por mercado.

Cada arquivo contém:
- Snapshots hourly de previsão (ECMWF, HRRR, METAR)
- Histórico de preços do mercado
- Detalhes da posição (entrada, stop, PnL)
- Resultado final da resolução

---

##⚠️ Aviso

Isso não é conselho financeiro. Mercados de predição carregam risco real. Execute a simulação completamente antes de comprometer capital real.

---

**Versão:** v2.0  
**Original:** https://github.com/alteregoeth-ai/weatherbot  
**Fork:** Delphus123/Tempo-bet

---

## Comandos Úteis

```bash
# Verificar se está rodando
ps aux | grep bot_v2

# Ver logs em tempo real
tail -f data/markets/*.json

# Limpar mercados antigos (cuidado!)
rm -rf data/markets/*.json

# Backup do estado
cp data/state.json data/state.json.bak
```
