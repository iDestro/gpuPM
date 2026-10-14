# Collapsible Desktop Sidebar

User scope: desktop expanded224px/collapsed64px navigation, icon tooltips, selected route unchanged, browser preference persisted; mobile drawer remains expanded. Reuse AntD controlled Sider/Menu, no new dependency or data API changes.

- [x] Write failing browser regression for collapse/width/current route, icons/English tooltip, reload preference, keyboard expand, scroll independence and mobile drawer after desktop collapse.
- [x] Add controlled Sider, separate desktop/mobile navigation rendering, localized toggle, bounded collapsed menu/brand/footer styles and safe localStorage handling.
- [x] Type/build and full Chrome regression; independent review; real both-entrance desktop/mobile checks without data writes.
- [x] Deploy static bundle, update test/deploy report, commit.
