<?php
// metar.php - same-origin METAR proxy (no CORS issues)
// Usage: metar.php?station=KPIT
//
// Returns JSON:
//   { "ok": true, "station": "KPIT", "metar": "KPIT ...", "cached": false }
//   { "ok": false, "error": "..." }

// HARDEN: prevent PHP warnings/notices from corrupting JSON output
error_reporting(0);
ini_set('display_errors', '0');

header("Content-Type: application/json; charset=utf-8");
// Keep/omit this as you like; same-origin pages won't need it
header("Access-Control-Allow-Origin: *");

function respond($code, $payload) {
  http_response_code($code);
  echo json_encode($payload, JSON_UNESCAPED_SLASHES);
  exit;
}

$station = isset($_GET["station"]) ? strtoupper(trim($_GET["station"])) : "";
if ($station === "" || !preg_match("/^[A-Z0-9]{4}$/", $station)) {
  respond(400, ["ok" => false, "error" => "Invalid station. Use 4-letter ICAO like KPIT."]);
}

$cacheDir = __DIR__ . "/cache";
if (!is_dir($cacheDir)) {
  @mkdir($cacheDir, 0755, true);
}

$cacheFile = $cacheDir . "/metar_" . $station . ".json";
$ttl = 60;

// Serve cache if fresh
if (is_file($cacheFile)) {
  $raw = @file_get_contents($cacheFile);
  $j = @json_decode($raw, true);
  if (is_array($j) && isset($j["ts"]) && isset($j["metar"])) {
    if ((time() - intval($j["ts"])) <= $ttl) {
      respond(200, ["ok" => true, "station" => $station, "metar" => $j["metar"], "cached" => true]);
    }
  }
}

// Fetch from AviationWeather API (raw METAR)
$url = "https://aviationweather.gov/api/data/metar?ids=" . urlencode($station) . "&format=raw&hours=2&taf=false";

$ctx = stream_context_create([
  "http" => [
    "method" => "GET",
    "timeout" => 8,
    "header" =>
      "User-Agent: PA-Airport-Status/1.0\r\n" .
      "Accept: text/plain\r\n"
  ]
]);

$data = @file_get_contents($url, false, $ctx);
if ($data === false) {
  respond(502, ["ok" => false, "error" => "Upstream fetch failed (aviationweather.gov)."]);
}

$metar = trim($data);

// If upstream returns HTML (rare, but happens during errors), reject it cleanly
if ($metar === "" || stripos($metar, "<html") !== false || stripos($metar, "<!doctype") !== false) {
  respond(502, ["ok" => false, "error" => "Upstream returned non-METAR content."]);
}

// Cache write (best-effort)
@file_put_contents($cacheFile, json_encode(["ts" => time(), "metar" => $metar], JSON_UNESCAPED_SLASHES));

respond(200, ["ok" => true, "station" => $station, "metar" => $metar, "cached" => false]);
