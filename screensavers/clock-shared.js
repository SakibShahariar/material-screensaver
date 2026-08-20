// Shared clock logic for all Material screensavers.
// Format is controlled by a URL query param the control script appends when
// launching (?format=12h or ?format=24h), driven by the GUI's AM/PM setting.
function pad2(n) { return n.toString().padStart(2, '0'); }

function formatClock() {
  const params = new URLSearchParams(location.search);
  const use12h = params.get('format') === '12h';
  const now = new Date();
  let h = now.getHours();
  let suffix = '';
  if (use12h) {
    suffix = h >= 12 ? 'PM' : 'AM';
    h = h % 12;
    if (h === 0) h = 12;
  }
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return {
    time: `${use12h ? h : pad2(h)}:${pad2(now.getMinutes())}`,
    suffix,
    date: `${days[now.getDay()]}, ${months[now.getMonth()]} ${now.getDate()}`,
  };
}

function startClock(clockEl, dateEl) {
  function tick() {
    const f = formatClock();
    clockEl.innerHTML = f.suffix ? `${f.time}<span class="ampm">${f.suffix}</span>` : f.time;
    dateEl.textContent = f.date;
  }
  tick();
  setInterval(tick, 1000);
}
