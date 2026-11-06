<?php
/*
 * BThinkX webmail push bridge.
 *
 * Lets a person who only uses webmail turn on new-mail notifications for their own mailbox. The browser calls
 * this page (same origin as the inbox); it trusts ONLY the mail server's own login session, never anything the
 * browser claims about who it is, and passes the subscription to the portal with a server-side secret.
 *
 *   GET  /bthinkx-push.php                         -> {"enabled":bool,"public_key":"...","mailbox":"..."}
 *   POST /bthinkx-push.php {"action":"subscribe","subscription":{...}}
 *   POST /bthinkx-push.php {"action":"unsubscribe","endpoint":"..."}
 *
 * Configuration (written by install.sh): bthinkx-push-config.php returns ['url' => portal base URL, 'token' => secret].
 */
require_once $_SERVER['DOCUMENT_ROOT'] . '/inc/prerequisites.inc.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function btx_out($code, $data) {
  http_response_code($code);
  echo json_encode($data);
  exit;
}

$cfgFile = __DIR__ . '/bthinkx-push-config.php';
$cfg = is_file($cfgFile) ? include $cfgFile : null;
if (!is_array($cfg) || empty($cfg['url']) || empty($cfg['token'])) {
  btx_out(503, ['error' => 'not_configured']);
}

// Only a mailbox owner signed in to this mail server (not an admin, not an API key).
if (!isset($_SESSION['mailcow_cc_role'], $_SESSION['mailcow_cc_username'])
    || $_SESSION['mailcow_cc_role'] !== 'user'
    || isset($_SESSION['mailcow_cc_api'])) {
  btx_out(401, ['error' => 'sign_in_required']);
}
$mailbox = strtolower($_SESSION['mailcow_cc_username']);

// Same-origin requests only.
$host = $_SERVER['HTTP_HOST'] ?? '';
$origin = $_SERVER['HTTP_ORIGIN'] ?? '';
if ($origin !== '' && $origin !== 'https://' . $host) {
  btx_out(403, ['error' => 'bad_origin']);
}
$method = $_SERVER['REQUEST_METHOD'];
if ($method === 'POST' && ($_SERVER['HTTP_X_REQUESTED_WITH'] ?? '') !== 'BThinkXMail') {
  btx_out(403, ['error' => 'bad_request']);
}

function btx_portal($cfg, $verb, $path, $payload = null) {
  $ch = curl_init(rtrim($cfg['url'], '/') . $path);
  $headers = ['Authorization: Bearer ' . $cfg['token'], 'Accept: application/json'];
  curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 8,
    CURLOPT_CONNECTTIMEOUT => 4,
    CURLOPT_CUSTOMREQUEST => $verb,
  ]);
  if ($payload !== null) {
    $headers[] = 'Content-Type: application/json';
    curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
  }
  curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
  $body = curl_exec($ch);
  $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
  curl_close($ch);
  return [$code, json_decode((string) $body, true)];
}

if ($method === 'GET') {
  list($code, $data) = btx_portal($cfg, 'GET', '/api/push/inbox/config/');
  if ($code !== 200 || !is_array($data)) {
    btx_out(502, ['error' => 'portal_unavailable']);
  }
  btx_out(200, ['enabled' => (bool) ($data['enabled'] ?? false), 'public_key' => $data['public_key'] ?? '', 'mailbox' => $mailbox]);
}

if ($method !== 'POST') {
  btx_out(405, ['error' => 'method_not_allowed']);
}

$in = json_decode(file_get_contents('php://input'), true);
if (!is_array($in)) {
  btx_out(400, ['error' => 'bad_json']);
}
$action = $in['action'] ?? '';

if ($action === 'subscribe') {
  $sub = $in['subscription'] ?? null;
  if (!is_array($sub) || empty($sub['endpoint']) || empty($sub['keys']['p256dh']) || empty($sub['keys']['auth'])) {
    btx_out(400, ['error' => 'bad_subscription']);
  }
  list($code, $data) = btx_portal($cfg, 'POST', '/api/push/inbox/subscribe/', [
    // The mailbox comes from the login session, never from the request.
    'mailbox' => $mailbox,
    'subscription' => ['endpoint' => $sub['endpoint'], 'keys' => ['p256dh' => $sub['keys']['p256dh'], 'auth' => $sub['keys']['auth']]],
    'user_agent' => substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 300),
  ]);
  btx_out($code === 201 ? 200 : ($code >= 400 && $code < 500 ? 400 : 502), ['ok' => $code === 201]);
}

if ($action === 'unsubscribe') {
  if (empty($in['endpoint'])) {
    btx_out(400, ['error' => 'bad_request']);
  }
  list($code, $data) = btx_portal($cfg, 'POST', '/api/push/inbox/unsubscribe/', ['mailbox' => $mailbox, 'endpoint' => $in['endpoint']]);
  btx_out($code === 200 ? 200 : 502, ['ok' => $code === 200]);
}

btx_out(400, ['error' => 'unknown_action']);
