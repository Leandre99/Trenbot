//+------------------------------------------------------------------+
//| TrenBot.mq5 : prise de position automatique dans MT5              |
//|                                                                    |
//| Même stratégie que signaux/signaux.py (bot de signaux) :           |
//|  ACHAT : la MM8 croise la MM21 vers le haut, puis la MM8, la MM21  |
//|          et le prix passent au-dessus de la MM50 (cassure sur la   |
//|          bougie EN COURS, sans attendre sa clôture) ; croisement   |
//|          de 30 bougies au plus ; un seul signal par croisement.    |
//|  VENTE : l'inverse.                                                |
//|  SL = prix -/+ 1,5 ATR(14), TP = prix +/- 1,5 ATR(14) (Wilder,     |
//|  calculé sur les 200 dernières bougies, comme le bot Python).      |
//|                                                                    |
//| Gestion : perte au SL = 2 % du solde ; si le lot minimum oblige à  |
//| risquer plus, jusqu'à 3 %, sinon le trade est sauté. 3 positions   |
//| au plus, jamais deux sur le même symbole. Les niveaux de SL/TP ne  |
//| sont jamais déplacés : trop proches -> trade sauté.                |
//|                                                                    |
//| Telegram : /demarrer, /arreter, /etat (accents acceptés), depuis   |
//| ta discussion seulement. ARRÊTÉ au premier lancement.              |
//+------------------------------------------------------------------+
#property copyright "TrenBot"
#property version   "1.00"
#property description "Stratégie MM8/MM21/MM50, SL/TP 1,5 ATR, 2 % de risque, pilotage par Telegram"

#include <Trade/Trade.mqh>

input string InpSymbols      = "Volatility 10 Index,Volatility 25 Index,Volatility 50 Index,Volatility 75 Index,Volatility 100 Index,Volatility 10 (1s) Index,Volatility 15 (1s) Index,Volatility 25 (1s) Index,Volatility 50 (1s) Index,Volatility 75 (1s) Index,Volatility 100 (1s) Index,Step Index,XAUUSD"; // Symboles (noms MT5, séparés par des virgules)
input string InpTimeframes   = "M15,M30";   // Unités de temps tradées
input double InpRisk         = 2.0;         // Risque par trade (% du solde)
input double InpRiskMax      = 3.0;         // Risque maximum si le lot minimum l'impose (%)
input int    InpMaxPositions = 3;           // Positions ouvertes au maximum
input double InpSlAtr        = 1.5;         // SL en ATR
input double InpTpAtr        = 1.5;         // TP en ATR
input int    InpAtrPeriod    = 14;          // Période ATR
input int    InpMaFast       = 8;           // MM rapide
input int    InpMaMid        = 21;          // MM moyenne
input int    InpMaSlow       = 50;          // MM lente
input int    InpCrossMax     = 30;          // Cassure au plus N bougies après le croisement
input int    InpBars         = 200;         // Bougies analysées (comme le bot Python)
input string InpTgToken      = "";          // Jeton du bot Telegram (@BotFather)
input string InpTgChat       = "";          // Identifiant de ta discussion Telegram
input string InpNom          = "MT5";       // Nom du compte dans les messages
input long   InpMagic        = 880821;      // Numéro magique des positions du robot

CTrade           g_trade;
string           g_syms[];
bool             g_symOk[];
ENUM_TIMEFRAMES  g_tfs[];
string           g_tfNames[];
bool             g_on     = false;
long             g_offset = 0;

#define GV_ON     "TrenBot_on"
#define GV_OFFSET "TrenBot_offset"

//+------------------------------------------------------------------+
int OnInit()
  {
   string parts[];
   int ns = StringSplit(InpSymbols, ',', parts);
   ArrayResize(g_syms, 0);
   ArrayResize(g_symOk, 0);
   for(int i = 0; i < ns; i++)
     {
      string s = parts[i];
      StringTrimLeft(s);
      StringTrimRight(s);
      if(s == "")
         continue;
      int k = ArraySize(g_syms);
      ArrayResize(g_syms, k + 1);
      ArrayResize(g_symOk, k + 1);
      g_syms[k]  = s;
      g_symOk[k] = SymbolSelect(s, true);
      if(!g_symOk[k])
         Print("TrenBot : symbole introuvable chez ce courtier : ", s);
     }
   int nt = StringSplit(InpTimeframes, ',', parts);
   ArrayResize(g_tfs, 0);
   ArrayResize(g_tfNames, 0);
   for(int i = 0; i < nt; i++)
     {
      string t = parts[i];
      StringTrimLeft(t);
      StringTrimRight(t);
      StringToUpper(t);
      ENUM_TIMEFRAMES tf = TfFromName(t);
      if(tf == PERIOD_CURRENT)
        {
         Print("TrenBot : unité de temps inconnue : ", t);
         continue;
        }
      int k = ArraySize(g_tfs);
      ArrayResize(g_tfs, k + 1);
      ArrayResize(g_tfNames, k + 1);
      g_tfs[k]     = tf;
      g_tfNames[k] = t;
     }
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(50);
   g_on     = GlobalVariableCheck(GV_ON) && GlobalVariableGet(GV_ON) > 0.5;
   g_offset = GlobalVariableCheck(GV_OFFSET) ? (long)GlobalVariableGet(GV_OFFSET) : 0;
   EventSetTimer(20);
   Print("TrenBot : Telegram -> jeton ", Tok() == "" ? "VIDE" : "renseigné", ", discussion InpTgChat = '", Chat(), "', DLL ",
         MQLInfoInteger(MQL_DLLS_ALLOWED) ? "autorisées (Telegram via Windows)" : "NON autorisées (Telegram via WebRequest, souvent en panne : autorise les DLL)");
   Tg(InpNom + " : TrenBot lancé. Trading automatique " + (g_on ? "EN MARCHE" : "ARRÊTÉ (envoie /demarrer)") +
      "\nSymboles trouvés : " + IntegerToString(CountOk()) + "/" + IntegerToString(ArraySize(g_syms)) +
      " | Unités : " + InpTimeframes);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   PollTelegram();
   if(!g_on)
      return;
   for(int i = 0; i < ArraySize(g_syms); i++)
     {
      if(!g_symOk[i])
         continue;
      for(int j = 0; j < ArraySize(g_tfs); j++)
         Check(g_syms[i], g_tfs[j], g_tfNames[j]);
     }
  }

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES TfFromName(const string t)
  {
   if(t == "M1")  return PERIOD_M1;
   if(t == "M5")  return PERIOD_M5;
   if(t == "M15") return PERIOD_M15;
   if(t == "M30") return PERIOD_M30;
   if(t == "H1")  return PERIOD_H1;
   if(t == "H4")  return PERIOD_H4;
   if(t == "D1")  return PERIOD_D1;
   return PERIOD_CURRENT;
  }

//+------------------------------------------------------------------+
int CountOk()
  {
   int n = 0;
   for(int i = 0; i < ArraySize(g_symOk); i++)
      if(g_symOk[i])
         n++;
   return n;
  }

//+------------------------------------------------------------------+
//| Moyenne mobile simple des clôtures se terminant à l'indice i     |
//+------------------------------------------------------------------+
double Sma(const double &c[], const int i, const int p)
  {
   double s = 0;
   for(int k = i - p + 1; k <= i; k++)
      s += c[k];
   return s / p;
  }

//+------------------------------------------------------------------+
//| MM8, MM21 et prix du bon côté de la MM50 à l'indice i            |
//+------------------------------------------------------------------+
bool Broke(const double &c[], const double &f[], const double &m[], const double &s[], const int i, const bool up)
  {
   if(i < InpMaSlow - 1)
      return false;
   if(up)
      return f[i] > s[i] && m[i] > s[i] && c[i] > s[i];
   return f[i] < s[i] && m[i] < s[i] && c[i] < s[i];
  }

//+------------------------------------------------------------------+
bool Above(const double &f[], const double &m[], const int i, const bool up)
  {
   if(i < InpMaMid - 1)
      return false;
   return up ? f[i] > m[i] : f[i] < m[i];
  }

//+------------------------------------------------------------------+
//| Bougie du dernier croisement MM8/MM21 dans ce sens, ou -1        |
//+------------------------------------------------------------------+
int LastCross(const double &f[], const double &m[], const int n, const bool up)
  {
   if(!Above(f, m, n - 1, up))
      return -1;
   int k = n - 1;
   while(k > 0 && Above(f, m, k - 1, up))
      k--;
   return k > 0 ? k : -1;
  }

//+------------------------------------------------------------------+
//| ATR de Wilder (comme pandas ewm(alpha=1/n, adjust=False))        |
//+------------------------------------------------------------------+
double AtrWilder(const MqlRates &r[], const int n, const int p)
  {
   double atr = r[0].high - r[0].low;
   for(int i = 1; i < n; i++)
     {
      double pc = r[i - 1].close;
      double tr = MathMax(r[i].high - r[i].low, MathMax(MathAbs(r[i].high - pc), MathAbs(r[i].low - pc)));
      atr += (tr - atr) / p;
     }
   return atr;
  }

//+------------------------------------------------------------------+
//| Signal sur la bougie en cours : 1 achat, -1 vente, 0 rien         |
//+------------------------------------------------------------------+
int Detect(const MqlRates &r[], const int n, double &price, double &sl, double &tp)
  {
   if(n < InpMaSlow + InpCrossMax + 2)
      return 0;
   double c[], f[], m[], s[];
   ArrayResize(c, n);
   ArrayResize(f, n);
   ArrayResize(m, n);
   ArrayResize(s, n);
   for(int i = 0; i < n; i++)
      c[i] = r[i].close;
   for(int i = 0; i < n; i++)
     {
      f[i] = i >= InpMaFast - 1 ? Sma(c, i, InpMaFast) : 0;
      m[i] = i >= InpMaMid  - 1 ? Sma(c, i, InpMaMid)  : 0;
      s[i] = i >= InpMaSlow - 1 ? Sma(c, i, InpMaSlow) : 0;
     }
   int side = 0;
   for(int pass = 0; pass < 2 && side == 0; pass++)
     {
      bool up = (pass == 0);
      if(!(Broke(c, f, m, s, n - 1, up) && !Broke(c, f, m, s, n - 2, up)))
         continue;                                   // la cassure de la MM50 se fait sur CETTE bougie
      int k = LastCross(f, m, n, up);
      if(k < 0 || n - 1 - k > InpCrossMax)
         continue;                                   // croisement trop ancien
      bool already = false;
      for(int i = k; i < n - 1; i++)
         if(Broke(c, f, m, s, i, up))
           {
            already = true;
            break;
           }
      if(already)
         continue;                                   // un seul signal par croisement
      side = up ? 1 : -1;
     }
   if(side == 0)
      return 0;
   double a = AtrWilder(r, n, InpAtrPeriod);
   if(a <= 0)
      return 0;
   price = c[n - 1];
   sl    = price - side * InpSlAtr * a;
   tp    = price + side * InpTpAtr * a;
   return side;
  }

//+------------------------------------------------------------------+
void Check(const string sym, const ENUM_TIMEFRAMES tf, const string tfName)
  {
   MqlRates r[];
   int n = CopyRates(sym, tf, 0, InpBars, r);     // r[0] = la plus ancienne, r[n-1] = bougie en cours
   if(n < InpMaSlow + InpCrossMax + 2)
      return;
   datetime cur = r[n - 1].time;
   if(TimeCurrent() - cur >= PeriodSeconds(tf))
      return;                                       // marché fermé : pas de bougie en cours
   string key = "TrenBot_" + sym + "_" + tfName;
   if(GlobalVariableCheck(key) && (datetime)GlobalVariableGet(key) == cur)
      return;                                       // déjà traité pour cette bougie
   double price = 0, sl = 0, tp = 0;
   int side = Detect(r, n, price, sl, tp);
   if(side == 0)
      return;
   GlobalVariableSet(key, (double)cur);             // une seule tentative par bougie, quoi qu'il arrive
   Execute(sym, tfName, side, price, sl, tp);
  }

//+------------------------------------------------------------------+
int VolumeDigits(const double step)
  {
   int d = 0;
   double s = step;
   while(d < 8 && MathAbs(s - MathRound(s)) > 1e-9)
     {
      s *= 10;
      d++;
     }
   return d;
  }

//+------------------------------------------------------------------+
//| Ouvre la position ; renvoie "" si prise, sinon la raison          |
//+------------------------------------------------------------------+
string Open(const string sym, const int side, double sl, double tp, string &detail)
  {
   MqlTick tk;
   if(!SymbolInfoTick(sym, tk))
      return "pas de prix disponible";
   int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);
   double entry = side > 0 ? tk.ask : tk.bid;
   if(side > 0 && !(sl < tk.bid && tp > tk.ask))
      return "le prix a déjà dépassé le SL ou le TP";
   if(side < 0 && !(sl > tk.ask && tp < tk.bid))
      return "le prix a déjà dépassé le SL ou le TP";
   double point   = SymbolInfoDouble(sym, SYMBOL_POINT);
   double minDist = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * point;
   if(MathAbs(entry - sl) <= minDist || MathAbs(tp - entry) <= minDist)
      return "SL ou TP trop proche (minimum du courtier)";
   double loss1 = 0;
   if(!OrderCalcProfit(side > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, 1.0, entry, sl, loss1))
      return "calcul du risque impossible";
   loss1 = MathAbs(loss1);
   if(loss1 <= 0)
      return "calcul du risque impossible";
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double vstp = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   int    vd   = VolumeDigits(vstp);
   double lots = MathFloor((bal * InpRisk / 100.0 / loss1) / vstp) * vstp;
   if(lots < vmin)
      lots = vmin;
   if(lots > vmax)
      lots = vmax;
   lots = NormalizeDouble(lots, vd);
   double risk = lots * loss1;
   double pct  = bal > 0 ? risk / bal * 100.0 : 999;
   if(pct > InpRiskMax + 1e-9)
      return StringFormat("lot minimum %s : risque de %.1f %% (> %.0f %%)", DoubleToString(vmin, vd), pct, InpRiskMax);
   double margin = 0;
   if(OrderCalcMargin(side > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, lots, entry, margin) &&
      margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
      return "marge insuffisante";
   g_trade.SetTypeFillingBySymbol(sym);
   bool ok = side > 0 ? g_trade.Buy(lots, sym, 0.0, sl, tp, "TrenBot")
                      : g_trade.Sell(lots, sym, 0.0, sl, tp, "TrenBot");
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED))
      return "refus du courtier : " + g_trade.ResultRetcodeDescription();
   detail = StringFormat("lot %s, risque %.2f %s (%.1f %%)", DoubleToString(lots, vd), risk,
                         AccountInfoString(ACCOUNT_CURRENCY), pct);
   return "";
  }

//+------------------------------------------------------------------+
void Execute(const string sym, const string tfName, const int side, const double price, const double sl, const double tp)
  {
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   string msg = (side > 0 ? "ACHAT " : "VENTE ") + sym + " (" + tfName + ") [" + InpNom + "]" +
                "\nPrix : " + DoubleToString(price, digits) +
                "\nSL : " + DoubleToString(sl, digits) +
                "\nTP : " + DoubleToString(tp, digits);
   int  count = 0;
   bool same  = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      count++;
      if(PositionGetString(POSITION_SYMBOL) == sym)
         same = true;
     }
   string reason = "", detail = "";
   if(count >= InpMaxPositions)
      reason = IntegerToString(count) + " positions déjà ouvertes";
   else
      if(same)
         reason = "position déjà ouverte sur ce marché";
      else
         reason = Open(sym, side, sl, tp, detail);
   msg += "\nPosition : " + (reason == "" ? "PRISE : " + detail : "NON PRISE : " + reason);
   Print("TrenBot : ", msg);
   Tg(msg);
  }

//+------------------------------------------------------------------+
//| Message quand une position du robot se ferme (TP, SL...)         |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;
   if(!HistoryDealSelect(trans.deal))
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic)
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
      return;
   long   reason = HistoryDealGetInteger(trans.deal, DEAL_REASON);
   double p = HistoryDealGetDouble(trans.deal, DEAL_PROFIT) + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION) +
              HistoryDealGetDouble(trans.deal, DEAL_SWAP);
   string why = reason == DEAL_REASON_TP ? "TP touché" : (reason == DEAL_REASON_SL ? "SL touché" : "fermée");
   string cur = AccountInfoString(ACCOUNT_CURRENCY);
   Tg(InpNom + " : " + HistoryDealGetString(trans.deal, DEAL_SYMBOL) + " " + why +
      "\nRésultat : " + (p >= 0 ? "+" : "") + DoubleToString(p, 2) + " " + cur +
      "\nSolde : " + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + " " + cur);
  }

//+------------------------------------------------------------------+
//| Telegram                                                         |
//+------------------------------------------------------------------+
string UrlEncode(const string s)
  {
   uchar b[];
   int len = StringToCharArray(s, b, 0, WHOLE_ARRAY, CP_UTF8);
   string out = "";
   for(int i = 0; i < len; i++)
     {
      uchar ch = b[i];
      if(ch == 0)
         break;
      if((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') ||
         ch == '-' || ch == '_' || ch == '.' || ch == '~')
         out += CharToString(ch);
      else
         out += StringFormat("%%%02X", ch);
     }
   return out;
  }

//+------------------------------------------------------------------+
string Trim(string s)
  {
   StringTrimLeft(s);
   StringTrimRight(s);
   StringReplace(s, "\"", "");
   return s;
  }

string Tok()  { return Trim(InpTgToken); }
string Chat() { return Trim(InpTgChat); }

//+------------------------------------------------------------------+
//| Explication lisible de la réponse de Telegram en cas d'échec      |
//+------------------------------------------------------------------+
string TgReason(const int code, const string js)
  {
   if(code >= 1000 || code == -1)
      return "code " + IntegerToString(code) + " (connexion impossible depuis MT5)" +
             (MQLInfoInteger(MQL_DLLS_ALLOWED) ? "" :
              " -> autorise les DLL : Tools > Options > Expert Advisors > Allow DLL imports, ET onglet Common du robot > Allow DLL imports, puis remets le robot sur le graphique");
   string why = js;
   int d = StringFind(js, "\"description\":\"");
   if(d >= 0)
     {
      d += 15;
      int e = StringFind(js, "\"", d);
      why = StringSubstr(js, d, e > d ? e - d : 200);
     }
   string hint = "";
   if(code == 401 || code == 404)
      hint = " -> jeton Telegram (InpTgToken) incorrect";
   else
      if(StringFind(why, "chat not found") >= 0)
         hint = " -> identifiant (InpTgChat) incorrect, ou le bot n'est pas dans ce canal / cette discussion";
      else
         if(StringFind(why, "not enough rights") >= 0 || StringFind(why, "not a member") >= 0 || code == 403)
            hint = " -> le bot doit être ADMINISTRATEUR du canal (ou tu dois avoir appuyé sur Démarrer dans le bot)";
         else
            if(code == 409)
               hint = " -> un autre programme lit déjà les messages de ce bot (webhook ou autre robot)";
   return "HTTP " + IntegerToString(code) + " : " + StringSubstr(why, 0, 200) + hint;
  }

//+------------------------------------------------------------------+
bool Tg(const string text)
  {
   if(Tok() == "" || Chat() == "")
     {
      Print("TrenBot : InpTgToken ou InpTgChat vide, aucun message Telegram envoyé");
      return false;
     }
   string url = "https://api.telegram.org/bot" + Tok() + "/sendMessage?chat_id=" + UrlEncode(Chat()) +
                "&text=" + UrlEncode(text);
   string js;
   int code = HttpGet(url, js);
   if(code != 200)
     {
      Print("TrenBot : Telegram refuse le message, ", TgReason(code, js));
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
//| HTTP GET. Les dernières versions de MT5 ont un bug : WebRequest   |
//| échoue (code 1009) sur certains sites HTTPS, dont Telegram. On    |
//| passe donc par la bibliothèque internet de Windows (wininet.dll)  |
//| quand les DLL sont autorisées, sinon par WebRequest.               |
//| Renvoie 200 si Telegram répond "ok":true.                          |
//+------------------------------------------------------------------+
#import "wininet.dll"
long InternetOpenW(string agent, int accessType, string proxy, string bypass, uint flags);
long InternetOpenUrlW(long hInternet, string url, string headers, int headersLength, uint flags, long context);
int  InternetReadFile(long hFile, uchar &buffer[], int bytesToRead, int &bytesRead[]);
int  InternetCloseHandle(long hInternet);
#import

int HttpGetWin(const string url, string &out)
  {
   out = "";
   long hNet = InternetOpenW("TrenBot", 1, "", "", 0);            // 1 = connexion directe
   if(hNet == 0)
      return 1001;
   uint flags = 0x80000000 | 0x04000000 | 0x00000100;               // RELOAD | NO_CACHE_WRITE | PRAGMA_NOCACHE
   long hUrl = InternetOpenUrlW(hNet, url, "", 0, flags, 0);
   if(hUrl == 0)
     {
      InternetCloseHandle(hNet);
      return 1002;
     }
   uchar buf[4096], all[];
   int rd[1];
   while(true)
     {
      rd[0] = 0;
      if(InternetReadFile(hUrl, buf, 4096, rd) == 0 || rd[0] <= 0)
         break;
      int n = ArraySize(all);
      ArrayResize(all, n + rd[0]);
      ArrayCopy(all, buf, n, 0, rd[0]);
     }
   InternetCloseHandle(hUrl);
   InternetCloseHandle(hNet);
   out = CharArrayToString(all, 0, WHOLE_ARRAY, CP_UTF8);
   if(StringFind(out, "\"ok\":true") >= 0)
      return 200;
   int ec = StringFind(out, "\"error_code\":");
   return ec >= 0 ? (int)StringToInteger(DigitsAt(out, ec + 13)) : 1003;
  }

int HttpGet(const string url, string &out)
  {
   if(MQLInfoInteger(MQL_DLLS_ALLOWED))
      return HttpGetWin(url, out);
   uchar data[], res[];
   string rh;
   ResetLastError();
   int code = WebRequest("GET", url, "", 10000, data, res, rh);
   out = CharArrayToString(res, 0, WHOLE_ARRAY, CP_UTF8);
   if(code == 200 && StringFind(out, "\"ok\":true") < 0)
      code = 400;
   return code;
  }

//+------------------------------------------------------------------+
string Normalize(string t)
  {
   StringToLower(t);
   string acc[] = {"\\u00e9", "\\u00e8", "\\u00ea", "\\u00c9", "\\u00c8", "\\u00ca", "é", "è", "ê", "É", "È", "Ê"};
   for(int i = 0; i < ArraySize(acc); i++)
      StringReplace(t, acc[i], "e");
   int at = StringFind(t, "@");
   if(at > 0)
      t = StringSubstr(t, 0, at);
   int sp = StringFind(t, " ");
   if(sp > 0)
      t = StringSubstr(t, 0, sp);
   return t;
  }

//+------------------------------------------------------------------+
string Etat()
  {
   int open = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t != 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         open++;
     }
   string missing = "";
   for(int i = 0; i < ArraySize(g_syms); i++)
      if(!g_symOk[i])
         missing += (missing == "" ? "" : ", ") + g_syms[i];
   string cur = AccountInfoString(ACCOUNT_CURRENCY);
   return InpNom + " : trading automatique " + (g_on ? "EN MARCHE" : "ARRÊTÉ") +
          "\nSolde : " + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + " " + cur +
          " | positions du robot : " + IntegerToString(open) + "/" + IntegerToString(InpMaxPositions) +
          "\nUnités : " + InpTimeframes + " | risque " + DoubleToString(InpRisk, 1) + " % (max " +
          DoubleToString(InpRiskMax, 1) + " %) | SL/TP " + DoubleToString(InpSlAtr, 1) + "/" + DoubleToString(InpTpAtr, 1) + " ATR" +
          "\nSymboles trouvés : " + IntegerToString(CountOk()) + "/" + IntegerToString(ArraySize(g_syms)) +
          (missing == "" ? "" : "\nIntrouvables : " + missing) +
          "\nTrading autorisé dans MT5 : " + (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED) ? "oui" : "NON (bouton Algo Trading)");
  }

//+------------------------------------------------------------------+
void Command(const string raw)
  {
   string cmd = Normalize(raw);
   if(cmd == "/demarrer")
     {
      g_on = true;
      GlobalVariableSet(GV_ON, 1);
      Tg(InpNom + " : trading automatique DÉMARRÉ. Les prochains signaux " + InpTimeframes + " seront pris.");
     }
   else
      if(cmd == "/arreter")
        {
         g_on = false;
         GlobalVariableSet(GV_ON, 0);
         Tg(InpNom + " : trading automatique ARRÊTÉ. Plus aucune position ne sera prise (celles ouvertes restent ouvertes).");
        }
      else
         if(cmd == "/etat")
            Tg(Etat());
  }

//+------------------------------------------------------------------+
//| Lit les messages reçus par le bot Telegram                       |
//+------------------------------------------------------------------+
void PollTelegram()
  {
   if(Tok() == "" || Chat() == "")
      return;
   string url = "https://api.telegram.org/bot" + Tok() + "/getUpdates?timeout=0&offset=" + IntegerToString(g_offset + 1);
   string js;
   int code = HttpGet(url, js);
   if(code != 200)
     {
      static datetime lastErr = 0;
      if(TimeCurrent() - lastErr > 600)                // au plus un message toutes les 10 min
        {
         lastErr = TimeCurrent();
         Print("TrenBot : lecture des commandes Telegram impossible, ", TgReason(code, js));
        }
      return;
     }
   string tag = "\"update_id\":";
   int pos = StringFind(js, tag);
   while(pos >= 0)
     {
      int p = pos + StringLen(tag);
      int next = StringFind(js, tag, p);
      string seg = next < 0 ? StringSubstr(js, p) : StringSubstr(js, p, next - p);
      long uid = StringToInteger(DigitsAt(seg, 0));
      if(uid > g_offset)
         g_offset = uid;
      string chat = "";
      int q = StringFind(seg, "\"chat\":{\"id\":");
      if(q >= 0)
         chat = DigitsAt(seg, q + 13);
      string txt = "";
      int t = StringFind(seg, "\"text\":\"");
      if(t >= 0)
        {
         t += 8;
         int e = t;
         int L = StringLen(seg);
         while(e < L)
           {
            ushort ch = StringGetCharacter(seg, e);
            if(ch == '\\')
              {
               e += 2;
               continue;
              }
            if(ch == '"')
               break;
            e++;
           }
         txt = StringSubstr(seg, t, e - t);
        }
      if(chat != "" && chat == Chat() && txt != "")
        {
         Print("TrenBot : commande reçue : ", txt);
         Command(txt);
        }
      else
         if(chat != "" && txt != "")
            Print("TrenBot : message ignoré, il vient de la discussion ", chat, " alors que InpTgChat = ", Chat(),
                  ". Si c'est bien toi, mets ", chat, " dans InpTgChat.");
      pos = next;
     }
   GlobalVariableSet(GV_OFFSET, (double)g_offset);
  }

//+------------------------------------------------------------------+
//| Nombre (éventuellement négatif) qui commence à la position p     |
//+------------------------------------------------------------------+
string DigitsAt(const string s, const int p)
  {
   int e = p;
   int L = StringLen(s);
   while(e < L)
     {
      ushort ch = StringGetCharacter(s, e);
      if(!((ch >= '0' && ch <= '9') || (ch == '-' && e == p)))
         break;
      e++;
     }
   return StringSubstr(s, p, e - p);
  }
//+------------------------------------------------------------------+
