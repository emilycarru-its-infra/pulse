// Masonry for a grid of cards of different heights: each card takes the height it needs and the
// next one fills the space beside a tall one, instead of every row being as tall as its tallest
// card. The grid keeps its columns and its order: cards are still placed left to right in the
// order they are in, so a list sorted for reading stays sorted. Each card spans as many small
// grid rows as its height needs; the page re-measures when cards change or the width does.
//
//   Pulse.masonry(document.getElementById("spaces"));
//
// The container keeps its own grid-template-columns and gap; .masonry in base.css adds the rest.

window.Pulse = window.Pulse || {};

Pulse.masonry = function (grid) {
  grid.classList.add("masonry");
  let frame = 0;
  const layout = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const style = getComputedStyle(grid);
      const row = parseFloat(style.gridAutoRows) || 4;
      // The vertical gap is the column gap, applied by the span: the grid's own row gap is 0.
      const gap = parseFloat(style.columnGap) || 0;
      for (const card of grid.children) {
        const h = card.getBoundingClientRect().height;
        const span = `span ${Math.max(1, Math.ceil((h + gap) / row))}`;
        if (card.style.gridRowEnd !== span) card.style.gridRowEnd = span;
      }
    });
  };
  const sizes = new ResizeObserver(layout);
  const watch = () => { sizes.disconnect(); sizes.observe(grid); for (const c of grid.children) sizes.observe(c); layout(); };
  new MutationObserver(watch).observe(grid, { childList: true });
  watch();
  return { layout };
};
