//+------------------------------------------------------------------+
//| TrendBotLines.mq5                                                |
//| Dessine sur le graphique les lignes de tendance W1 / D1 / H4     |
//| calculees par le bot Python (fichier trendbot_lines.csv).        |
//| Haussieres = vert, baissieres = rouge. W1 epais, D1 moyen, H4 fin.|
//+------------------------------------------------------------------+
#property copyright "trendbot"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

input string FileName   = "trendbot_lines.csv"; // fichier ecrit par le bot (dossier Common\Files)
input int    RefreshSec = 5;                    // verification du fichier toutes les N secondes
input color  UpColor    = clrLimeGreen;
input color  DownColor  = clrTomato;
input bool   ShowW1     = true;
input bool   ShowD1     = true;
input bool   ShowH4     = true;

const string PFX = "tb_";
long g_lastModify = 0;
string g_lastSymbol = "";

int OnInit()
{
   EventSetTimer(RefreshSec);
   Redraw(true);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, PFX);
}

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[],
                const double &open[], const double &high[], const double &low[], const double &close[],
                const long &tick_volume[], const long &volume[], const int &spread[])
{
   return rates_total;
}

void OnTimer()
{
   Redraw(false);
}

bool TfEnabled(const string tf)
{
   if(tf == "W1") return ShowW1;
   if(tf == "D1") return ShowD1;
   if(tf == "H4") return ShowH4;
   return true;
}

int TfWidth(const string tf)
{
   if(tf == "W1") return 3;
   if(tf == "D1") return 2;
   return 1;
}

void Redraw(const bool force)
{
   int h = FileOpen(FileName, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      Comment("TrendBotLines : fichier ", FileName, " introuvable (lance le bot Python)");
      return;
   }
   long modify = FileGetInteger(h, FILE_MODIFY_DATE);
   if(!force && modify == g_lastModify && g_lastSymbol == _Symbol)
   {
      FileClose(h);
      return;
   }
   g_lastModify = modify;
   g_lastSymbol = _Symbol;

   ObjectsDeleteAll(0, PFX);

   string prevKey = "";
   datetime prevT = 0;
   double prevP = 0;
   int count = 0;
   string lastLabelKey = "";

   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(line == "") continue;
      string p[];
      if(StringSplit(line, ',', p) < 7) continue;
      if(p[0] != _Symbol) continue;
      string tf = p[1], side = p[2];
      if(!TfEnabled(tf)) continue;
      int touches = (int)StringToInteger(p[3]);
      datetime t = (datetime)StringToInteger(p[5]);
      double price = StringToDouble(p[6]);
      string key = tf + "_" + side;

      if(key == prevKey)
      {
         string name = PFX + key + "_" + p[4];
         if(ObjectCreate(0, name, OBJ_TREND, 0, prevT, prevP, t, price))
         {
            ObjectSetInteger(0, name, OBJPROP_COLOR, side == "up" ? UpColor : DownColor);
            ObjectSetInteger(0, name, OBJPROP_WIDTH, TfWidth(tf));
            ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
            ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
            ObjectSetInteger(0, name, OBJPROP_BACK, true);
            ObjectSetString(0, name, OBJPROP_TOOLTIP, tf + (side == "up" ? " haussiere" : " baissiere") + " (" + IntegerToString(touches) + " touches)");
            count++;
         }
         // etiquette au bout de la ligne
         if(lastLabelKey != key + p[4])
         {
            string lbl = PFX + "lbl_" + key;
            ObjectDelete(0, lbl);
            if(ObjectCreate(0, lbl, OBJ_TEXT, 0, t, price))
            {
               ObjectSetString(0, lbl, OBJPROP_TEXT, tf + (side == "up" ? " UP" : " DN") + " (" + IntegerToString(touches) + ")");
               ObjectSetInteger(0, lbl, OBJPROP_COLOR, side == "up" ? UpColor : DownColor);
               ObjectSetInteger(0, lbl, OBJPROP_FONTSIZE, 8);
               ObjectSetInteger(0, lbl, OBJPROP_SELECTABLE, false);
            }
            lastLabelKey = key + p[4];
         }
      }
      prevKey = key;
      prevT = t;
      prevP = price;
   }
   FileClose(h);
   Comment("TrendBotLines : ", count, " segments | mis a jour ", TimeToString(TimeLocal(), TIME_MINUTES));
   ChartRedraw(0);
}
