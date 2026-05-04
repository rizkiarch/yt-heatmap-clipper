// ═══════════════════════════════════════════════════════════════════════
// SIDEBAR
// ═══════════════════════════════════════════════════════════════════════
const sidebar = document.getElementById('appSidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebarClose = document.getElementById('sidebarClose');
const sidebarOverlay = document.getElementById('sidebarOverlay');
const sidebarCollapseBtn = document.getElementById('sidebarCollapseBtn');
const appContainer = document.querySelector('.app-container');
const SIDEBAR_COLLAPSED_KEY = 'yt-clipper-sidebar-collapsed';

function isMobile() {
  return window.innerWidth <= 768;
}

function openSidebar() {
  sidebar.classList.add('open');
  sidebarOverlay.classList.add('visible');
  document.body.style.overflow = 'hidden';
}

function closeSidebar() {
  sidebar.classList.remove('open');
  sidebarOverlay.classList.remove('visible');
  document.body.style.overflow = '';
}

function toggleSidebar() {
  if (sidebar.classList.contains('open')) {
    closeSidebar();
  } else {
    openSidebar();
  }
}

function toggleCollapseSidebar() {
  sidebar.classList.toggle('collapsed');
  appContainer.classList.toggle('sidebar-collapsed');
  appContainer.classList.remove('with-sidebar');
  if (sidebar.classList.contains('collapsed')) {
    appContainer.classList.add('sidebar-collapsed');
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, 'true');
  } else {
    appContainer.classList.add('with-sidebar');
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, 'false');
  }
}

function setActiveMenu() {
  const path = window.location.pathname;
  document.querySelectorAll('.sidebar-item').forEach(item => {
    item.classList.remove('active');
    const href = item.getAttribute('href');
    if (href === path || (path === '/' && href === '/dashboard')) {
      item.classList.add('active');
    }
  });
}

function initSidebar() {
  // Set active menu based on current URL
  setActiveMenu();

  // Restore collapsed state from localStorage (desktop only)
  if (!isMobile()) {
    const wasCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true';
    if (wasCollapsed) {
      sidebar.classList.add('collapsed');
      appContainer.classList.add('sidebar-collapsed');
    } else {
      appContainer.classList.add('with-sidebar');
    }
  }

  // Show toggle button on mobile
  if (isMobile()) {
    sidebarToggle.classList.add('visible');
  } else {
    sidebar.classList.add('open');
  }
}

// Event listeners
sidebarToggle.addEventListener('click', openSidebar);
sidebarClose.addEventListener('click', closeSidebar);
sidebarOverlay.addEventListener('click', closeSidebar);
if (sidebarCollapseBtn) {
  sidebarCollapseBtn.addEventListener('click', toggleCollapseSidebar);
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && sidebar.classList.contains('open')) {
    closeSidebar();
  }
});

// Handle window resize
let resizeTimeout;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimeout);
  resizeTimeout = setTimeout(() => {
    const mobile = isMobile();
    if (mobile) {
      closeSidebar();
      sidebarToggle.classList.add('visible');
      sidebar.classList.remove('collapsed');
      appContainer.classList.remove('with-sidebar', 'sidebar-collapsed');
    } else {
      sidebarToggle.classList.remove('visible');
      const wasCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true';
      if (wasCollapsed) {
        sidebar.classList.add('collapsed');
        appContainer.classList.add('sidebar-collapsed');
      } else {
        appContainer.classList.add('with-sidebar');
        sidebar.classList.add('open');
      }
    }
  }, 150);
});

initSidebar();
