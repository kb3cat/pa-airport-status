<?php
// metar.php - simple same-origin METAR proxy (no CORS issues)
//
// Usage: metar.php?station=KMDT
//
// Notes:
// - Caches for 60 seconds to reduce load
// - Returns JSON: { ok: true, station: "...", metar: "..." } or { ok:false, error:"..." }

header("Content-Type: application/json; charset=utf-8");
header("Access-Control-Allow-Origin: *"); // safe because same-origin is intended; harmless otherwise.

$station = isset($_GET["station"]) ? strtoupper(trim($_GET["station"])) : "";
if ($station === "" || !preg_match("/^[A-Z0-9]{4}$/", $station)) {
  http_response_code(400);
  echo json_encode(["ok" => false, "error" => "Invalid station. Use 4-letter ICAO like KMDT."]);
  exit;
}

$cacheDir = __DIR__ . "/cache";
if (!is_dir($cacheDir)) @mkdir($cacheDir, 0755, true);

$cacheFile = $cacheDir . "/metar_" . $station . ".json";
$ttl = 60; // seconds

// Serve cache if fresh
if (is_file($cacheFile)) {
  $raw = file_get_contents($cacheFile);
  $j = json_decode($raw, true);
  if (is_array($j) && isset($j["ts"]) && (time() - intval($j["ts"]) <= $ttl)) {
    echo json_encode(["ok" => true, "station" => $station, "metar" => $j["metar"], "cached" => true]);
    exit;
  }
}

// Fetch from AviationWeather API
$url = "https://aviationweather.gov/api/data/metar?ids=" . urlencode($station) . "&format=raw&hours=2&taf=false";

$ctx = stream_context_create([
  "http" => [
    "method" => "GET",
    "timeout" => 8,
    "header" => "User-Agent: PA-Airport-Status/1.0\r\n"
  ]
]);

$data = @file_get_contents($url, false, $ctx);
if ($data === false) {
  http_response_code(502);
  echo json_encode(["ok" => false, "error" => "Upstream fetch failed."]);
  exit;
}

$metar = trim($data);
if ($metar === "") {
  http_response_code(404);
  echo json_encode(["ok" => false, "error" => "No METAR returned for station."]);
  exit;
}

// Write cache
@file_put_contents($cacheFile, json_encode(["ts" => time(), "metar" => $metar]));

echo json_encode(["ok" => true, "station" => $station, "metar" => $metar, "cached" => false]);
