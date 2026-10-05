/* Progressive enhancement: links and case details also work without JavaScript. */
(() => {
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('#site-navigation');
  const header = document.querySelector('.site-header');
  if (!toggle || !nav || !header) return;
  const mobile = window.matchMedia('(max-width: 767px)');
  let open = false;
  const render = () => {
    toggle.hidden = !mobile.matches;
    nav.hidden = mobile.matches && !open;
    toggle.setAttribute('aria-expanded', String(mobile.matches && open));
    toggle.querySelector('span').textContent = open ? '−' : '+';
  };
  toggle.addEventListener('click', () => { open = !open; render(); });
  nav.addEventListener('click', event => {
    if (event.target.closest('a')) { open = false; render(); }
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && open) {
      open = false; render(); toggle.focus();
    }
  });
  document.addEventListener('click', event => {
    if (open && !header.contains(event.target)) { open = false; render(); }
  });
  const sync = () => { open = false; render(); };
  if (mobile.addEventListener) mobile.addEventListener('change', sync);
  else mobile.addListener(sync);
  render();
})();
