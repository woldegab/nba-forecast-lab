from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from unittest import mock

import live_forecast
from live_forecast import (LEDGER_FILE, START_FILE, SUMMARY_FILE, combine, games_from_results, main,
                           parse_espn, parse_schedule, parse_scoreboard, read_ledger, start_ratings,
                           summarize, update, write_ledger)

START = dict(season='2026-27', parameters=dict(initial_rating=1500.0, k=20.0,
             home_advantage=65.0, retention=0.75),
             ratings={'1': dict(team='AAA', rating=1550.0), '2': dict(team='BBB', rating=1450.0),
                      '3': dict(team='CCC', rating=1500.0)})


def game(game_id, tipoff, home=1, away=2, status=1, scores=(None, None), **extra):
    tricode = {1: 'AAA', 2: 'BBB', 3: 'CCC'}
    return dict(gameId=game_id, gameStatus=status, gameStatusText='', gameDateTimeUTC=tipoff,
                homeTeam=dict(teamId=home, teamTricode=tricode[home], score=scores[0]),
                awayTeam=dict(teamId=away, teamTricode=tricode[away], score=scores[1]), **extra)


def schedule(*games, season='2026-27'):
    return dict(leagueSchedule=dict(seasonYear=season, gameDates=[dict(gameDate='x', games=list(games))]))


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


class ScheduleTests(unittest.TestCase):
    def test_uses_eastern_date_and_regular_season_only(self):
        games = parse_schedule(schedule(
            game('0022600001', '2026-11-27T00:30:00Z'),       # 7:30 pm ET on Nov 26
            game('0012600001', '2026-10-05T23:00:00Z')))      # preseason, ignored
        self.assertEqual([g['game_id'] for g in games], ['0022600001'])
        self.assertEqual(games[0]['game_date'], '2026-11-26')

    def test_rejects_wrong_season_and_bad_scores(self):
        with self.assertRaises(ValueError):
            parse_schedule(schedule(game('0022600001', '2026-11-27T00:30:00Z'), season='2025-26'))
        with self.assertRaises(ValueError):
            parse_schedule(schedule(game('0022600001', '2026-11-27T00:30:00Z', status=3, scores=(100, 100))))

    def test_neutral_flag(self):
        games = parse_schedule(schedule(game('0022600001', '2026-11-27T00:30:00Z', isNeutral=True)))
        self.assertEqual(games[0]['neutral_site'], 1)


class UpdateTests(unittest.TestCase):
    def test_forecasts_only_todays_unstarted_games(self):
        games = parse_schedule(schedule(
            game('0022600001', '2026-11-27T00:30:00Z'),                       # tonight
            game('0022600002', '2026-11-28T00:30:00Z', home=3, away=1)))       # tomorrow
        ledger, notes = update(games, START, {}, at('2026-11-26T15:00:00'))
        self.assertEqual(list(ledger), ['0022600001'])
        self.assertEqual(ledger['0022600001']['mode'], 'live')
        self.assertEqual(notes, [])

    def test_saved_forecast_never_changes_and_result_is_added(self):
        first = parse_schedule(schedule(game('0022600001', '2026-11-27T00:30:00Z')))
        ledger, _ = update(first, START, {}, at('2026-11-26T15:00:00'))
        saved = dict(ledger['0022600001'])
        final = parse_schedule(schedule(game('0022600001', '2026-11-27T00:30:00Z', status=3, scores=(90, 99))))
        later, _ = update(final, START, ledger, at('2026-11-27T15:00:00'))
        row = later['0022600001']
        for field in ('home_win_probability', 'home_rating', 'predicted_at_utc', 'mode'):
            self.assertEqual(row[field], saved[field])
        self.assertEqual((row['home_score'], row['away_score'], row['actual_home_win']), (90, 99, 0))

    def test_earlier_results_update_ratings_but_same_day_results_do_not(self):
        games = parse_schedule(schedule(
            game('0022600001', '2026-11-25T00:30:00Z', status=3, scores=(80, 120)),   # Nov 24: upset
            game('0022600002', '2026-11-27T00:00:00Z', status=3, scores=(80, 120)),   # today, already final
            game('0022600003', '2026-11-27T01:00:00Z')))                               # today, later
        ledger, _ = update(games, START, {}, at('2026-11-27T00:30:00'))
        self.assertEqual(ledger['0022600001']['mode'], 'backfill')
        self.assertNotIn('0022600002', ledger)          # finished today: not live, not yet backfilled
        live = ledger['0022600003']
        self.assertEqual(live['mode'], 'live')
        self.assertLess(float(live['home_rating']), 1550.0)   # lost the Nov 24 game

    def test_back_to_back_lowers_tired_teams_chance_but_not_stored_rating(self):
        start = dict(START, parameters=dict(START['parameters'], back_to_back=50.0))
        games = parse_schedule(schedule(
            game('0022600001', '2026-11-26T00:30:00Z', home=1, away=3, status=3, scores=(100, 100 - 1)),  # Nov 25
            game('0022600002', '2026-11-27T00:30:00Z', home=1, away=2)))                              # Nov 26
        rested = update(games, START, {}, at('2026-11-26T15:00:00'))[0]['0022600002']
        tired = update(games, start, {}, at('2026-11-26T15:00:00'))[0]['0022600002']
        self.assertEqual(tired['home_rating'], rested['home_rating'])
        drop = float(rested['home_win_probability']) - float(tired['home_win_probability'])
        self.assertTrue(0.04 < drop < 0.09, drop)   # 50 Elo points near a 70% favorite

    def test_unfinished_earlier_game_blocks_new_forecasts(self):
        games = parse_schedule(schedule(
            game('0022600001', '2026-11-26T00:30:00Z', status=2),
            game('0022600002', '2026-11-27T00:30:00Z')))
        ledger, notes = update(games, START, {}, at('2026-11-26T15:00:00'))
        self.assertEqual(ledger, {})
        self.assertTrue(notes)

    def test_summary_separates_live_from_backfill(self):
        games = parse_schedule(schedule(
            game('0022600001', '2026-11-25T00:30:00Z', status=3, scores=(120, 80)),
            game('0022600002', '2026-11-27T00:30:00Z')))
        ledger, _ = update(games, START, {}, at('2026-11-26T15:00:00'))
        summary = summarize(ledger, at('2026-11-26T15:00:00'))
        self.assertEqual(summary['backfill']['games'], 1)
        self.assertEqual(summary['live']['games'], 0)
        self.assertEqual(summary['pending'], 1)


class StartAndFilesTests(unittest.TestCase):
    def test_start_ratings_regress_toward_mean(self):
        archive = [dict(game_id='1', game_date='2026-01-01', season='2025-26', home_team_id=1,
                        away_team_id=2, home_team='AAA', away_team='BBB', home_score=110,
                        away_score=100, neutral_site=1)]
        from evaluate_elo import ORIGINAL_PARAMETERS
        ratings = start_ratings(archive, ORIGINAL_PARAMETERS)
        self.assertEqual(ratings['1'], dict(team='AAA', rating=1507.5))
        self.assertEqual(ratings['2'], dict(team='BBB', rating=1492.5))

    def test_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / START_FILE).write_text(json.dumps(START))
            (path / 'schedule.json').write_text(json.dumps(schedule(game('0022600001', '2026-11-27T00:30:00Z'))))
            args = ['update', '--live-dir', folder, '--input', str(path / 'schedule.json'),
                    '--now', '2026-11-26T15:00:00+00:00']
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 0)            # rerun adds nothing
            self.assertEqual(len(read_ledger(path / LEDGER_FILE)), 1)
            self.assertTrue((path / SUMMARY_FILE).exists())

    def test_ledger_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / LEDGER_FILE
            games = parse_schedule(schedule(game('0022600001', '2026-11-27T00:30:00Z')))
            ledger, _ = update(games, START, {}, at('2026-11-26T15:00:00'))
            write_ledger(path, ledger)
            path.write_text(path.read_text() + path.read_text().splitlines()[1] + '\n')
            with self.assertRaises(ValueError):
                read_ledger(path)


def log_row(game_id, team_id, abbr, matchup, wl, pts, date='2026-10-20'):
    # Same fields nba_api's LeagueGameLog returned for 2026-27.
    return dict(SEASON_ID='22026', TEAM_ID=team_id, TEAM_ABBREVIATION=abbr, GAME_ID=game_id,
                GAME_DATE=date, MATCHUP=matchup, WL=wl, PTS=pts)


def board(*games):
    # Same shape as nba_api's ScoreboardV3().get_dict().
    out = []
    for g in games:
        g = dict(g)
        g['gameTimeUTC'] = g.pop('gameDateTimeUTC')
        out.append(g)
    return dict(scoreboard=dict(gameDate='x', games=out))


class NbaApiSourceTests(unittest.TestCase):
    def test_results_identify_home_and_validate(self):
        games = games_from_results([log_row('0022600001', 2, 'BBB', 'BBB @ AAA', 'L', 113),
                                    log_row('0022600001', 1, 'AAA', 'AAA vs. BBB', 'W', 121)])
        g = games[0]
        self.assertEqual((g['home_team'], g['away_team'], g['home_score'], g['away_score']), ('AAA', 'BBB', 121, 113))
        self.assertEqual((g['game_date'], g['neutral_site'], g['status']), ('2026-10-20', 0, 3))

    def test_both_teams_away_means_neutral(self):
        games = games_from_results([log_row('0022600002', 2, 'BBB', 'BBB @ AAA', 'W', 100),
                                    log_row('0022600002', 1, 'AAA', 'AAA @ BBB', 'L', 90)])
        self.assertEqual(games[0]['neutral_site'], 1)

    def test_results_reject_inconsistent_win_loss(self):
        with self.assertRaises(ValueError):
            games_from_results([log_row('0022600001', 2, 'BBB', 'BBB @ AAA', 'W', 113),
                                log_row('0022600001', 1, 'AAA', 'AAA vs. BBB', 'W', 121)])

    def test_scoreboard_keeps_tipoff_time(self):
        games = parse_scoreboard(board(game('0022600064', '2026-11-28T00:00:00Z'),
                                       game('0062600001', '2026-11-28T00:00:00Z')))   # not regular season
        self.assertEqual([g['game_id'] for g in games], ['0022600064'])
        self.assertEqual(games[0]['game_date'], '2026-11-27')

    def test_combine_prefers_results_but_keeps_scoreboard_time_and_designation(self):
        results = games_from_results([log_row('0022600050', 2, 'BBB', 'BBB @ AAA', 'L', 99, '2026-11-25'),
                                      log_row('0022600050', 1, 'AAA', 'AAA vs. BBB', 'W', 101, '2026-11-25')])
        scoreboard = parse_scoreboard(board(game('0022600050', '2026-11-26T00:30:00Z', status=3, scores=(101, 99))))
        merged = combine(results, scoreboard)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['tipoff'].isoformat(), '2026-11-26T00:30:00+00:00')
        self.assertEqual(merged[0]['home_team'], 'AAA')

    def test_download_and_update_end_to_end(self):
        results = [log_row('0022600050', 2, 'BBB', 'BBB @ AAA', 'L', 99, '2026-11-25'),
                   log_row('0022600050', 1, 'AAA', 'AAA vs. BBB', 'W', 101, '2026-11-25')]
        boards = {'2026-11-25': board(game('0022600050', '2026-11-26T00:30:00Z', status=3, scores=(101, 99))),
                  '2026-11-26': board(game('0022600060', '2026-11-27T00:30:00Z', home=3, away=1))}
        with mock.patch.object(live_forecast, 'fetch_results', return_value=results), \
                mock.patch.object(live_forecast, 'fetch_scoreboard', side_effect=boards.get):
            games = live_forecast.download_games(at('2026-11-26T15:00:00'))
        ledger, notes = update(games, START, {}, at('2026-11-26T15:00:00'))
        self.assertEqual(notes, [])
        self.assertEqual(ledger['0022600050']['mode'], 'backfill')
        self.assertEqual(ledger['0022600060']['mode'], 'live')
        self.assertGreater(float(ledger['0022600060']['away_rating']), 1550.0)   # won on Nov 25

    def test_unfinished_game_yesterday_blocks_forecasts(self):
        boards = {'2026-11-25': board(game('0022600050', '2026-11-26T03:00:00Z', status=2)),
                  '2026-11-26': board(game('0022600060', '2026-11-27T00:30:00Z', home=3, away=1))}
        with mock.patch.object(live_forecast, 'fetch_results', return_value=[]), \
                mock.patch.object(live_forecast, 'fetch_scoreboard', side_effect=boards.get):
            games = live_forecast.download_games(at('2026-11-26T15:00:00'))
        ledger, notes = update(games, START, {}, at('2026-11-26T15:00:00'))
        self.assertNotIn('0022600060', ledger)
        self.assertTrue(notes)


TEAM_IDS = {'AAA': 1, 'BBB': 2, 'CCC': 3, 'NYK': 4}


def espn_event(event_id, date, home='AAA', away='BBB', state='pre', scores=('0', '0'), season_type=2, name=None):
    # Same shape as ESPN's scoreboard (checked against the 2026-11-27 feed).
    completed = state == 'post'
    status = dict(type=dict(state=state, completed=completed,
                            name=name or ('STATUS_FINAL' if completed else 'STATUS_SCHEDULED')))
    return dict(id=event_id, date=date, season=dict(year=2027, type=season_type), status=status,
                competitions=[dict(neutralSite=False, status=status, competitors=[
                    dict(homeAway='home', score=scores[0], team=dict(id='x', abbreviation=home)),
                    dict(homeAway='away', score=scores[1], team=dict(id='y', abbreviation=away))])])


def espn(*events):
    return dict(events=list(events))


class EspnSourceTests(unittest.TestCase):
    def test_maps_espn_codes_and_skips_other_season_types(self):
        games = parse_espn(espn(espn_event('401', '2026-11-28T00:00Z', home='NY'),
                                espn_event('402', '2026-11-28T00:00Z', season_type=1)), TEAM_IDS)
        self.assertEqual(len(games), 1)
        g = games[0]
        self.assertEqual((g['game_id'], g['home_team'], g['home_team_id'], g['game_date'], g['status']),
                         ('espn-401', 'NYK', 4, '2026-11-27', 1))

    def test_final_scores_and_postponed(self):
        final, postponed = parse_espn(espn(
            espn_event('401', '2026-11-27T00:30Z', state='post', scores=('110', '104')),
            espn_event('402', '2026-11-27T00:30Z', name='STATUS_POSTPONED')), TEAM_IDS)
        self.assertEqual((final['status'], final['home_score'], final['away_score']), (3, 110, 104))
        self.assertTrue(postponed['postponed'])

    def test_unknown_team_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_espn(espn(espn_event('401', '2026-11-28T00:00Z', home='ZZZ')), TEAM_IDS)

    def test_saved_results_feed_ratings_without_duplicates_across_sources(self):
        # Ledger already has Nov 25 from nba_api (backfill). ESPN reports the same game under its own ID.
        backfill = parse_schedule(schedule(game('0022600050', '2026-11-26T00:30:00Z', status=3, scores=(80, 120))))
        ledger, _ = update(backfill, START, {}, at('2026-11-26T05:00:00'))
        self.assertEqual(list(ledger), ['0022600050'])
        games = parse_espn(espn(
            espn_event('401', '2026-11-26T00:30Z', state='post', scores=('80', '120')),   # same game
            espn_event('402', '2026-11-27T00:30Z', home='AAA', away='CCC')), TEAM_IDS)   # today
        later, notes = update(games, START, ledger, at('2026-11-26T15:00:00'))
        self.assertEqual(notes, [])
        self.assertEqual(sorted(later), ['0022600050', 'espn-402'])   # no duplicate of Nov 25
        self.assertLess(float(later['espn-402']['home_rating']), 1550.0)   # AAA's loss counted once

    def test_cli_uses_espn_by_default(self):
        board_days = {'2026-11-25': espn(), '2026-11-26': espn(espn_event('402', '2026-11-27T00:30Z'))}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(live_forecast, 'fetch_espn', side_effect=board_days.get), \
                redirect_stdout(io.StringIO()):
            (Path(folder) / START_FILE).write_text(json.dumps(START))
            self.assertEqual(main(['update', '--live-dir', folder, '--now', '2026-11-26T15:00:00+00:00']), 0)
            self.assertEqual(list(read_ledger(Path(folder) / LEDGER_FILE)), ['espn-402'])


class NextGamesTests(unittest.TestCase):
    def test_finds_first_day_with_games(self):
        days = {'2026-11-27': espn(), '2026-11-28': espn(espn_event('401', '2026-11-29T00:00Z'),
                                                           espn_event('402', '2026-11-29T00:30Z', home='CCC'))}
        found = live_forecast.find_next_games(at('2026-11-26T15:00:00'), START, days=5,
                                              fetch=lambda day: days.get(day, espn()))
        self.assertEqual(found, dict(date='2026-11-28', games=2))

    def test_none_when_nothing_scheduled(self):
        self.assertIsNone(live_forecast.find_next_games(at('2026-11-26T15:00:00'), START, days=3, fetch=lambda day: espn()))

    def test_cli_saves_next_games_on_an_empty_day(self):
        days = {'2026-11-25': espn(), '2026-11-26': espn(),
                '2026-11-27': espn(espn_event('402', '2026-11-28T00:30Z'))}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(live_forecast, 'fetch_espn', side_effect=lambda day: days.get(day, espn())), \
                redirect_stdout(io.StringIO()):
            (Path(folder) / START_FILE).write_text(json.dumps(START))
            self.assertEqual(main(['update', '--live-dir', folder, '--now', '2026-11-26T15:00:00+00:00']), 0)
            summary = json.loads((Path(folder) / SUMMARY_FILE).read_text())
        self.assertEqual(summary['next_games'], dict(date='2026-11-27', games=1))


if __name__ == '__main__':
    unittest.main()
