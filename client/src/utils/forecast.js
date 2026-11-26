// A game whose win chance rounds to 50% is shown as even, with no favorite.
export const isEven = (game) => Math.round(game.home_win_probability * 100) === 50;
