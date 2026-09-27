// Login page logic (plan 8.1). Vanilla JS, no third-party code.
(function () {
  'use strict';
  var params = new URLSearchParams(location.search);
  var slug = (params.get('c') || '').toLowerCase();
  var ret = params.get('return') || ('/c/' + slug + '/');
  var $ = function (id) { return document.getElementById(id); };
  var email = '';

  if (!/^[a-z0-9-]{3,32}$/.test(slug)) {
    $('step-email').hidden = true;
    say('This sign-in link is incomplete. Open the link you were given again.', 'error');
    return;
  }
  $('for').textContent = slug === 'internal'
    ? 'Version 1 internal previews and dashboard'
    : 'Enablement material for ' + slug.replace(/-/g, ' ');

  function say(text, kind) {
    var m = $('msg');
    m.textContent = text || '';
    m.className = 'msg' + (kind ? ' ' + kind : '');
  }

  async function sha256Hex(text) {
    var buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf)).map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');
  }

  // CloudFront OAC to Lambda function URLs requires the body hash on POST.
  async function post(path, payload) {
    var body = JSON.stringify(payload);
    var res = await fetch(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json', 'x-amz-content-sha256': await sha256Hex(body) },
      body: body
    });
    var data = {};
    try { data = await res.json(); } catch (e) { /* empty */ }
    return { status: res.status, data: data };
  }

  function busy(form, on) {
    form.querySelectorAll('button, input').forEach(function (el) { el.disabled = on; });
  }

  $('step-email').addEventListener('submit', async function (e) {
    e.preventDefault();
    email = $('email').value.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { say('Enter a valid email address.', 'error'); return; }
    busy(this, true); say('Sending…');
    try {
      var r = await post('/auth/api/request', { c: slug, email: email });
      if (r.status === 429) { say(r.data.message || 'Too many requests. Try again later.', 'error'); return; }
      if (r.status !== 202) { say(r.data.message || 'Something went wrong. Try again.', 'error'); return; }
      $('step-email').hidden = true;
      $('step-code').hidden = false;
      $('sent-to').textContent = 'If ' + email + ' is allowed to access this site, we have sent it a code.';
      if (r.data.demo_code) {
        $('demo').hidden = false;
        $('demo').textContent = 'Demo mode: your code is ' + r.data.demo_code;
      }
      say('');
      $('code').focus();
    } catch (err) {
      say('Could not reach the sign-in service. Check your connection and try again.', 'error');
    } finally { busy(this, false); }
  });

  $('step-code').addEventListener('submit', async function (e) {
    e.preventDefault();
    var code = $('code').value.replace(/\D/g, '');
    if (code.length !== 6) { say('Enter the 6-digit code from the email.', 'error'); return; }
    busy(this, true); say('Checking…');
    try {
      var r = await post('/auth/api/verify', { c: slug, email: email, code: code, 'return': ret });
      if (r.status === 200 && r.data.redirect) { say('Signed in.', 'ok'); location.replace(r.data.redirect); return; }
      say(r.data.message || 'That code is not valid.', 'error');
    } catch (err) {
      say('Could not reach the sign-in service. Check your connection and try again.', 'error');
    } finally { busy(this, false); }
  });

  $('restart').addEventListener('click', function () {
    $('step-code').hidden = true; $('step-email').hidden = false; $('demo').hidden = true;
    $('code').value = ''; say(''); $('email').focus();
  });
})();
