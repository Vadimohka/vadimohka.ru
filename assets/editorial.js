/* Progressive enhancement: links and content also work without JavaScript. */
(() => {
  'use strict';
  const toggle = document.querySelector('[data-nav-toggle]');
  const nav = document.querySelector('[data-nav]');
  if (!toggle || !nav) return;
  const mobile = window.matchMedia('(max-width: 760px)');

  const setOpen = open => {
    toggle.setAttribute('aria-expanded', String(open));
    toggle.querySelector('span').textContent = open ? '−' : '+';
    nav.hidden = mobile.matches && !open;
  };
  const sync = () => {
    toggle.hidden = !mobile.matches;
    setOpen(false);
  };
  toggle.addEventListener('click', () => {
    setOpen(toggle.getAttribute('aria-expanded') !== 'true');
  });
  nav.addEventListener('click', event => {
    if (mobile.matches && event.target.closest('a')) setOpen(false);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && mobile.matches && toggle.getAttribute('aria-expanded') === 'true') {
      setOpen(false);
      toggle.focus();
    }
  });
  if (typeof mobile.addEventListener === 'function') {
    mobile.addEventListener('change', sync);
  } else {
    mobile.addListener(sync);
  }
  sync();
})();
