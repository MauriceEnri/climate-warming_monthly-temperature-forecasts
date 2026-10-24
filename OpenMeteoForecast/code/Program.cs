using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using System.IO;
using System.Net.NetworkInformation;
using System.Diagnostics;

class Program
{
    private static readonly Dictionary<string, string> ModelIds = new()
    {
        { "ICON", "icon_seamless" },
        { "GFS",  "gfs_seamless" },
        { "IFS",  "ecmwf_ifs025" },
        { "AIFS", "ecmwf_aifs025_single" },
        { "UKMO", "ukmo_seamless" },
        { "GEM" , "gem_global" }
    };

    static readonly string LogFile = @"C:\Temp\modellprognose.log";

    static void Log(string msg)
    {
        Directory.CreateDirectory(@"C:\Temp");
        File.AppendAllText(LogFile,
            $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {msg}{Environment.NewLine}");
    }

    static void LogSystemInfo()
    {
        Log("=== SYSTEMINFO START ===");
        Log($"User: {Environment.UserName}");
        Log($"Machine: {Environment.MachineName}");
        Log($"BaseDirectory: {AppContext.BaseDirectory}");
        Log($"CurrentDirectory: {Environment.CurrentDirectory}");
        Log($"Is64BitProcess: {Environment.Is64BitProcess}");
        Log($"ProcessorCount: {Environment.ProcessorCount}");
        Log($"OSVersion: {Environment.OSVersion}");
        Log($"CommandLine: {Environment.CommandLine}");
        Log($"SessionID: {Process.GetCurrentProcess().SessionId}");
        Log("=== SYSTEMINFO END ===");
    }

    static void LogNetworkStatus()
    {
        Log("=== NETWORK CHECK START ===");

        try
        {
            bool networkUp = NetworkInterface.GetIsNetworkAvailable();
            Log($"NetworkAvailable: {networkUp}");

            foreach (var ni in NetworkInterface.GetAllNetworkInterfaces())
            {
                Log($"Interface: {ni.Name}, Status: {ni.OperationalStatus}, Type: {ni.NetworkInterfaceType}");
            }

            using var client = new HttpClient();
            client.Timeout = TimeSpan.FromSeconds(5);

            var test = client.GetAsync("https://www.google.com").Result;
            Log($"HTTP Test Status: {test.StatusCode}");
        }
        catch (Exception ex)
        {
            Log($"NETWORK ERROR: {ex.Message}");
        }

        Log("=== NETWORK CHECK END ===");
    }

    private static string? DetectRun(DateTime now)
    {
        var t = now.TimeOfDay;

        if (t < new TimeSpan(12, 00, 0))
            return "00z";

        if (t >= new TimeSpan(12, 0, 0) && t <= new TimeSpan(17, 0, 0))
            return "06z";

        if (t >= new TimeSpan(19, 0, 0))
            return "12z";

        return null;
    }

    static async Task RunForecastAsync()
    {
        Log("=== PROGRAMM START ===");
        LogSystemInfo();
        LogNetworkStatus();

        try
        {
            Environment.CurrentDirectory = AppContext.BaseDirectory;
            Log($"Set CurrentDirectory to: {Environment.CurrentDirectory}");

            DateTime today = DateTime.Today;
            Log($"Today: {today:yyyy-MM-dd}");

            string? run = DetectRun(DateTime.Now);
            Log($"DetectRun() returned: {run ?? "NULL"}");

            if (run == null)
            {
                Log("Abbruch: Ungültiges Zeitfenster für Modelllauf.");
                return;
            }

            Log($"Automatischer Lauf erkannt: {run}");

            using var client = new HttpClient();
            client.Timeout = TimeSpan.FromSeconds(60);
            Log("HttpClient initialisiert.");

            Log("Beginne MOSMIX…");

            var mosmixService = new MosmixService(run);
            Log("MosmixService erstellt.");

            var mosmixLatest = mosmixService.LoadMosmixDataLatest(today);
            Log("LoadMosmixDataLatest() abgeschlossen.");

            MosmixData mosmix = mosmixLatest;
            Log("MOSMIX geladen.");

            var blPrinter = new MosmixBundeslandDailyPrinter();
            Log("BundeslandPrinter erstellt.");
            blPrinter.PrintBundeslandDailyMeans(mosmix);
            Log("BundeslandDailyMeans gedruckt.");

            var printer = new MosmixConsolePrinter();
            Log("ConsolePrinter erstellt.");
            printer.PrintAverageTmaxForToday(mosmix.AllStations, today);
            printer.PrintTop10WarmestStationsForNextDay(mosmix.AllStations, today, true);
            printer.PrintRegionTopsForNextDay(mosmix.AllStations, today, true);
            printer.PrintStationsWithDailyHeatwave30Plus(mosmix.AllStations);
            printer.PrintSunshine16Stations(mosmix.Sunshine16Stations, mosmix.DailySunMean, today);

            Log("MOSMIX-Auswertungen abgeschlossen.");

            var omService = new OpenMeteoService(client, ModelIds);
            Log("OpenMeteoService erstellt.");

            var omData = await omService.LoadOpenMeteoData(today);
            Log("Open-Meteo geladen.");

            mosmixService.SaveMosmixForecastsToDatabase(mosmix, today, $"MOSMIX_{run}");
            Log("MOSMIX-DB-Speicherung abgeschlossen.");

            omService.PrintModelRuns(omData);
            Log("ModelRuns gedruckt.");

            var sunDiagramService = new SunDiagramService(run);
            var rainDiagramService = new RainDiagramService(run);
            var tempDiagramService = new TempDiagramService(run);

            Log("DiagramServices erstellt.");

            string sunLink = sunDiagramService.CreateSunDiagram(mosmix, today);
            Log($"SunDiagram erstellt: {sunLink}");

            string rainLink = rainDiagramService.CreateRainDiagram(mosmix, omData, today);
            Log($"RainDiagram erstellt: {rainLink}");

            string tempLink = tempDiagramService.CreateTempDiagram(mosmix, omData, today);
            Log($"TempDiagram erstellt: {tempLink}");

            Log("Diagramme erstellt.");
            Log("=== PROGRAMM ENDE ERFOLGREICH ===");
        }
        catch (Exception ex)
        {
            Log($"FEHLER: {ex.Message}");
            Log($"STACKTRACE: {ex.StackTrace}");
            Log("=== PROGRAMM ENDE MIT FEHLER ===");
        }
    }

    static async Task Main()
    {
        await RunForecastAsync();
    }
}
