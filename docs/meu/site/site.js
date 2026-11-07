const menuButton = document.querySelector('.menu-toggle');
const navigation = document.querySelector('#main-nav');
menuButton.addEventListener('click', () => {
  const expanded = menuButton.getAttribute('aria-expanded') !== 'true';
  menuButton.setAttribute('aria-expanded', String(expanded));
  navigation.dataset.open = String(expanded);
});
navigation.addEventListener('click', event => {
  if (!event.target.closest('a')) return;
  menuButton.setAttribute('aria-expanded', 'false');
  navigation.dataset.open = 'false';
});

const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
function selectTab(tab, focus = false) {
  for (const item of tabs) {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected));
    item.tabIndex = selected ? 0 : -1;
    document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
  }
  if (focus) tab.focus();
}
for (const tab of tabs) {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', event => {
    const index = tabs.indexOf(tab);
    const destinations = { ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1 };
    if (!(event.key in destinations)) return;
    event.preventDefault();
    selectTab(tabs[destinations[event.key]], true);
  });
}
for (const link of document.querySelectorAll('[data-show-tab]')) {
  link.addEventListener('click', () => selectTab(document.getElementById(link.dataset.showTab)));
}

const dialog = document.querySelector('.lightbox');
for (const button of document.querySelectorAll('.screenshot-button')) {
  button.addEventListener('click', () => {
    const source = button.querySelector('img');
    const enlarged = dialog.querySelector('img');
    enlarged.src = source.src;
    enlarged.alt = source.alt;
    document.getElementById('lightbox-title').textContent = source.alt;
    dialog.showModal();
  });
}
dialog.querySelector('button').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => {
  const bounds = dialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
});
