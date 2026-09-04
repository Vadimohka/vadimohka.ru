document.documentElement.classList.remove('no-js');
const body = document.body;
const header = document.querySelector('.site-header');
const navToggle = document.querySelector('[data-nav-toggle]');
const navPanel = document.querySelector('[data-nav-panel]');
const mobileNav = window.matchMedia('(max-width: 900px)');

if (navToggle && navPanel) {
  const closeNav = () => {
    navToggle.setAttribute('aria-expanded', 'false');
    body.classList.remove('nav-open');
    if (mobileNav.matches) {
      navPanel.setAttribute('aria-hidden', 'true');
    } else {
      navPanel.removeAttribute('aria-hidden');
    }
  };

  const openNav = () => {
    navToggle.setAttribute('aria-expanded', 'true');
    body.classList.add('nav-open');
    navPanel.setAttribute('aria-hidden', 'false');
  };

  const syncNav = () => {
    if (mobileNav.matches) {
      const expanded = navToggle.getAttribute('aria-expanded') === 'true';
      navPanel.setAttribute('aria-hidden', String(!expanded));
      body.classList.toggle('nav-open', expanded);
    } else {
      closeNav();
    }
  };

  navToggle.addEventListener('click', () => {
    const expanded = navToggle.getAttribute('aria-expanded') === 'true';
    if (expanded) {
      closeNav();
    } else {
      openNav();
    }
  });

  navPanel.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
      closeNav();
    });
  });

  document.addEventListener('click', event => {
    if (!mobileNav.matches || !body.classList.contains('nav-open')) return;
    if (header && !header.contains(event.target)) {
      closeNav();
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      closeNav();
      navToggle.focus();
    }
  });

  if (typeof mobileNav.addEventListener === 'function') {
    mobileNav.addEventListener('change', syncNav);
  } else if (typeof mobileNav.addListener === 'function') {
    mobileNav.addListener(syncNav);
  }

  syncNav();
}

const onScroll = () => {
  if (!header) return;
  header.classList.toggle('is-scrolled', window.scrollY > 16);
};
onScroll();
window.addEventListener('scroll', onScroll, { passive: true });

const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const observer = !prefersReducedMotion && 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('is-visible');
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 }) : null;

document.querySelectorAll('.reveal').forEach(el => {
  if (!observer) {
    el.classList.add('is-visible');
  } else {
    observer.observe(el);
  }
});
