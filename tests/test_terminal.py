import copy
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

from engine import database, feeds, intelligence, lab, models, quant, research, risk, autotrader, exchange
from engine import settings, secrets
from engine import process_lock


class QuantTests(unittest.TestCase):
    def test_decimal_ev_probability_is_not_value(self):
        self.assertLess(quant.ev(.75, 1.25), 0)
        self.assertGreater(quant.ev(.42, 2.6), 0)
        self.assertAlmostEqual(quant.ev(.5, 2), 0)
        self.assertAlmostEqual(quant.ev(.55, 2, .1), .045)

    def test_american_odds(self):
        self.assertEqual(quant.american_to_decimal(150), 2.5)
        self.assertAlmostEqual(quant.american_to_decimal(-200), 1.5)

    def test_invalid_numbers_cannot_enter_ledger(self):
        for value in (float('nan'), float('inf'), -1, True):
            with self.assertRaises(ValueError):
                quant.probability(value)
        for value in (0, 1, -2, float('nan')):
            with self.assertRaises(ValueError):
                quant.decimal(value)

    def test_no_vig_against_published_reference(self):
        # CRAN implied package examples, independent reference values.
        odds = [4.2, 3.7, 1.95]
        expected = {'proportional': [.2331556,.2646631,.5021813],
                    'power': [.2311414,.2630644,.5057941],
                    'shin': [.2315811,.2635808,.5048382]}
        for method, reference in expected.items():
            actual = quant.no_vig(odds, method)
            self.assertAlmostEqual(sum(actual), 1, places=8)
            for a, b in zip(actual, reference):
                # Published Shin uses a loose JS convergence tolerance (eps**.25).
                self.assertAlmostEqual(a, b, delta=2e-5 if method=='shin' else 2e-6)

    def test_shin_two_way_and_fair_market(self):
        self.assertAlmostEqual(quant.no_vig([1.9,1.9], 'shin')[0], .5)
        self.assertEqual(quant.no_vig([2,2], 'shin'), [.5,.5])

    def test_min_price_kelly_and_clv(self):
        self.assertAlmostEqual(quant.kelly(.55, 2), .025)
        self.assertAlmostEqual(quant.ev(.5, quant.min_odds(.5,.02)), .02)
        self.assertAlmostEqual(quant.clv(2.2,2), .1)
        self.assertEqual(quant.kelly(.5,2), 0)

    def test_calibration_known_scores(self):
        rows = [{'p': .8, 'y': 1}, {'p': .2, 'y': 0}]
        metrics = quant.calibration(rows)
        self.assertAlmostEqual(metrics['brier'], .04)
        self.assertAlmostEqual(metrics['log_loss'], -__import__('math').log(.8))
        self.assertIsNone(quant.calibration([])['brier'])

    def test_monte_carlo_groups_mutually_exclusive_bets(self):
        bets = [{'event_id':'x','selection':'HOME','p':.5,'odds':2,'stake':10},
                {'event_id':'x','selection':'AWAY','p':.5,'odds':2,'stake':10}]
        result = quant.monte_carlo(bets,100,200)
        self.assertEqual(result['p05'],100)
        self.assertEqual(result['p95'],100)
        self.assertEqual(result['ruin_probability'],0)
        with self.assertRaises(ValueError):
            quant.monte_carlo([bets[0],bets[0]],100,100)

    def test_deposits_are_not_profit_or_drawdown(self):
        bets=[{'settled_at':2,'stake':10,'pnl':-10,'ev':.1,'status':'LOST'}]
        curve=quant.cashflow_curve(bets,[{'created_at':1,'amount':100},{'created_at':3,'amount':1000}])
        self.assertEqual(curve['curve'][-1]['equity'],1090)
        self.assertAlmostEqual(curve['drawdown'],.1)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = database.PATH
        database.PATH = os.path.join(self.tmp.name,'test.sqlite3')
        database.initialize()
        intelligence._last_scan.clear()
        self.now = time.time()
        self.events = feeds.demo_events(self.now)
        intelligence.deposit('DEMO',1000)
        self.decisions = intelligence.ingest(self.events,'DEMO',self.now)

    def tearDown(self):
        database.PATH = self.old
        self.tmp.cleanup()

    def bet_decision(self):
        return next(d for d in self.decisions if d['event_id']==self.events[0]['id'] and d['selection']=='HOME')

    def test_qualifying_demo_has_price_sensitive_stake(self):
        d = self.bet_decision()
        self.assertEqual(d['action'],'BET')
        self.assertGreater(d['odds'],d['min_odds'])
        self.assertLessEqual(d['stake'],10)
        self.assertNotIn(d['bookmaker'],d['estimate']['inputs']['reference_books'])

    def test_paper_unvalidated_defaults_to_watch(self):
        events = copy.deepcopy(self.events)
        for e in events:
            e['mode']='PAPER'
        intelligence.deposit('PAPER',1000)
        decisions = intelligence.ingest(events,'PAPER',self.now)
        self.assertFalse(any(d['action']=='BET' for d in decisions))
        self.assertTrue(any(d['action']=='WATCH' for d in decisions))

    def test_source_modes_cannot_mix(self):
        with self.assertRaises(ValueError):
            intelligence.ingest(self.events,'REAL')
        self.assertEqual(intelligence.overview('REAL')['account']['deposits'],0)

    def test_stale_prices_and_started_events_pass(self):
        event = copy.deepcopy(self.events[0])
        for book in event['books']:
            book['updated_at']=self.now-301
        out = intelligence.evaluate(event,{'equity':1000,'cash':1000,'halted':False},[],{}, {'state':'PAPER'}, now=self.now)
        self.assertTrue(all(d['action']=='PASS' for d in out))
        event['start']=self.now-1
        out = intelligence.evaluate(event,{'equity':1000,'cash':1000,'halted':False},[],{}, {'state':'PAPER'}, now=self.now)
        self.assertTrue(all(d['action']=='PASS' for d in out))

    def test_idempotent_atomic_bet_and_no_duplicate_selection(self):
        d = self.bet_decision()
        first = intelligence.place(d['id'],'DEMO','unique-test-001')
        duplicate = intelligence.place(d['id'],'DEMO','unique-test-001')
        self.assertEqual(first['bet']['id'],duplicate['bet']['id'])
        self.assertTrue(duplicate['duplicate'])
        with self.assertRaises(ValueError):
            intelligence.place(d['id'],'DEMO','different-test-key')
        s = intelligence.overview('DEMO')
        self.assertEqual(len(s['bets']),1)
        self.assertEqual(s['account']['cash'],1000-first['bet']['stake'])

    def test_concurrent_entries_do_not_double_spend(self):
        d = self.bet_decision()
        def enter(n):
            try:
                return intelligence.place(d['id'],'DEMO',f'concurrent-key-{n}')
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(enter,range(4)))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_kill_switch_blocks_entry(self):
        intelligence.set_halt('DEMO',True)
        with self.assertRaises(ValueError):
            intelligence.place(self.bet_decision()['id'],'DEMO','blocked-test-key')

    def test_bet_expiry_blocks_entry(self):
        with patch('engine.intelligence.time.time',return_value=self.now+121):
            with self.assertRaises(ValueError):
                intelligence.place(self.bet_decision()['id'],'DEMO','expired-test-key')

    def test_settlement_and_clv_require_observed_prestart_quotes(self):
        d = self.bet_decision()
        placed = intelligence.place(d['id'],'DEMO','settlement-test-key')['bet']
        event = copy.deepcopy(self.events[0])
        near_start = event['start']-60
        event['received_at']=near_start
        for book in event['books']:
            book['updated_at']=near_start
            if book['key']==placed['bookmaker']:
                book['prices']['HOME']=2.1
        intelligence.ingest([event],'DEMO',near_start)
        result = intelligence.settle('DEMO',event['id'],'HOME',now=event['start']+7200)
        self.assertEqual(result['settled'],1)
        s = intelligence.overview('DEMO')
        bet = s['bets'][0]
        self.assertEqual(bet['status'],'WON')
        self.assertAlmostEqual(bet['pnl'],placed['stake']*(placed['odds']-1))
        self.assertEqual(bet['closing_odds'],2.1)
        self.assertAlmostEqual(bet['clv'],placed['odds']/2.1-1)
        self.assertTrue(intelligence.settle('DEMO',event['id'],'HOME',now=event['start']+7200)['duplicate'])
        with self.assertRaises(ValueError):
            intelligence.settle('DEMO',event['id'],'AWAY',now=event['start']+7200)

    def test_unobserved_closing_price_stays_null(self):
        d = self.bet_decision()
        intelligence.place(d['id'],'DEMO','missing-close-test')
        event = self.events[0]
        intelligence.settle('DEMO',event['id'],'AWAY',now=event['start']+7200)
        bet = intelligence.overview('DEMO')['bets'][0]
        self.assertIsNone(bet['closing_odds'])
        self.assertEqual(bet['pnl'],-bet['stake'])

    def test_void_refunds_and_not_in_calibration(self):
        d = self.bet_decision()
        intelligence.place(d['id'],'DEMO','void-test-key')
        intelligence.settle('DEMO',d['event_id'],void=True,now=d['start']+7200)
        s = intelligence.overview('DEMO')
        self.assertEqual(s['account']['cash'],1000)
        self.assertEqual(s['metrics']['calibration']['n'],0)

    def test_model_calibration_includes_pass_predictions_without_bets(self):
        event=self.events[1]
        intelligence.settle('DEMO',event['id'],'HOME',now=event['start']+7200)
        snapshot=intelligence.overview('DEMO')
        self.assertEqual(snapshot['metrics']['bets'],0)
        self.assertEqual(snapshot['model_calibration']['events'],1)
        self.assertEqual(snapshot['model_calibration']['n'],3)

    def test_provider_budget_prevents_network_request(self):
        with patch.object(settings,'load',return_value={'odds_daily_request_limit':0}),patch.object(feeds.requests,'get') as http:
            with self.assertRaises(ValueError):
                feeds.fetch_live('fake-test-key',['soccer_epl'])
            http.assert_not_called()

    def test_immutable_predictions(self):
        import sqlite3
        with database.connection(write=True) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE decisions SET action='BET'")

    def test_original_bet_and_deposits_cannot_be_rewritten(self):
        import sqlite3
        decision=next(o for o in self.decisions if o['action']=='BET')
        intelligence.place(decision['id'],'DEMO','immutable-bet-test')
        for statement in ("UPDATE bets SET stake=1000", "UPDATE bets SET p=1", "DELETE FROM bets", "UPDATE deposits SET amount=10000", "DELETE FROM deposits"):
            with database.connection(write=True) as db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)

    def test_live_strategy_gate(self):
        with self.assertRaises(ValueError):
            intelligence.update_strategy('REAL','LIVE')

    def test_invalid_csv_cannot_partially_import(self):
        with self.assertRaises(ValueError):
            lab.import_results('id,league\nx,y')
        self.assertEqual(lab.status()['historical_matches'],0)

    def test_historical_odds_cannot_be_from_future(self):
        raw={'id':'hist','sport_key':'soccer_epl','home_team':'A','away_team':'B','commence_time':self.now+10,
             'received_at':self.now+20,'bookmakers':[]}
        with self.assertRaises(ValueError):
            lab.import_odds([raw])


class RiskTests(unittest.TestCase):
    def test_correlated_team_and_event_caps(self):
        account={'equity':1000,'cash':900,'halted':False}
        opp={'event_id':'e','selection':'HOME','sport':'football','league':'epl','p_lower':.8,'odds':2}
        event_map={'e':{'home':'A','away':'B'},'f':{'home':'A','away':'C'}}
        bets=[{'event_id':'f','selection':'HOME','sport':'football','league':'epl','market':'h2h','stake':30,'status':'OPEN','placed_at':time.time()}]
        stake,_=risk.propose(opp,account,bets,event_map)
        self.assertEqual(stake,0)
        bets[0]['event_id']='e';bets[0]['selection']='AWAY';bets[0]['stake']=20
        stake,_=risk.propose(opp,account,bets,event_map)
        self.assertEqual(stake,0)


class CryptoSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=autotrader.STATE_PATH
        autotrader.STATE_PATH=os.path.join(self.tmp.name,'crypto.json')

    def tearDown(self):
        autotrader.STATE_PATH=self.old
        self.tmp.cleanup()

    def test_failed_flatten_keeps_position_and_pending_intent(self):
        state=autotrader._default(100)
        state['positions']=[{'symbol':'BTC/EUR','amount':1,'entry':100,'cost':100,'live':True}]
        autotrader._save(state)
        with patch.object(exchange,'live_enabled',return_value=True),patch.object(exchange,'get_price',return_value=100),patch.object(exchange,'market_sell',side_effect=TimeoutError):
            autotrader.flatten()
            s=autotrader._load()
            self.assertTrue(s['halted'])
            self.assertEqual(len(s['positions']),1)
            self.assertIn('pending_order',s)
            with self.assertRaises(ValueError):
                autotrader.flatten()

    def test_live_balance_failure_never_uses_paper_cash(self):
        with patch.object(exchange,'live_enabled',return_value=True),patch.object(exchange,'get_quote_balance',side_effect=TimeoutError):
            with self.assertRaises(RuntimeError):
                autotrader._available_cash(autotrader._default(100))

    def test_live_gate_and_unconfirmed_fill(self):
        with patch.object(exchange,'live_enabled',return_value=False):
            with self.assertRaises(ValueError):
                exchange.market_buy('BTC/EUR',10)
        with self.assertRaises(RuntimeError):
            exchange._confirmed_fill({'id':'x','status':'open','filled':0},'BTC/EUR','buy')

    def test_partial_sell_cannot_erase_full_position(self):
        order={'id':'partial','status':'closed','filled':.5,'cost':50,'average':100,
               'fee':{'currency':'EUR','cost':.1}}
        with self.assertRaises(RuntimeError):
            exchange._confirmed_fill(order,'BTC/EUR','sell',expected_amount=1)
        self.assertEqual(exchange._confirmed_fill(order,'BTC/EUR','sell',expected_amount=.5)['amount'],.5)

    def test_risk_halt_survives_midnight(self):
        state=autotrader._default(100)
        state.update(halted=True,halt_reason='kill switch',day='2000-01-01')
        autotrader._ensure_risk_window(state,100)
        self.assertTrue(state['halted'])

    def test_empty_bankroll_is_not_a_loss_but_actual_zero_equity_is(self):
        empty=autotrader._default(0)
        self.assertIsNone(autotrader._risk_status(empty,0)['daily_return_pct'])
        self.assertIsNone(autotrader._apply_risk_guard(empty,0))
        funded=autotrader._default(100)
        funded['day']=autotrader._today()
        self.assertEqual(autotrader._risk_status(funded,0)['total_return_pct'],-100)
        self.assertIsNotNone(autotrader._apply_risk_guard(funded,0))
        self.assertTrue(funded['halted'])

    def test_live_mode_cannot_sell_paper_position(self):
        s=autotrader._default(100)
        s['positions']=[{'symbol':'BTC/EUR','live':False}]
        with patch.object(exchange,'live_enabled',return_value=True):
            with self.assertRaises(ValueError):
                autotrader._check_mode(s)


class ResearchTests(unittest.TestCase):
    def test_llm_cannot_supply_probability(self):
        with patch.object(research,'available',return_value=True):
            self.assertEqual(research.estimate_probabilities({},[.4,.6]),[.4,.6])

    def test_budget_reserves_before_request_and_blocks_second_call(self):
        with (tempfile.TemporaryDirectory() as tmp,
              patch.object(research,'USAGE_PATH',os.path.join(tmp,'usage.json')),
              patch.object(research,'available',return_value=True),
              patch.object(research.settings,'load',return_value={'ai_daily_call_limit':1,'ai_daily_token_budget':12000}),
              patch.object(research.anthropic,'Anthropic',side_effect=TimeoutError) as sdk):
            decision={'reasons':['Known signal'],'counterarguments':['Unknown edge']}
            with self.assertRaises(ValueError):
                research.explain(decision)
            self.assertEqual(research.usage_status()['calls'],1)
            self.assertGreater(research.usage_status()['reserved_tokens'],0)
            with self.assertRaises(ValueError):
                research.explain(decision)
            self.assertEqual(sdk.call_count,1)


class ChronologyTests(unittest.TestCase):
    def test_complete_import_evaluation_and_frozen_holdout(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(database,'PATH',os.path.join(tmp,'lab.sqlite3')):
            database.initialize()
            start=1600000000
            lines=['id,league,home,away,start,available_at,home_goals,away_goals,source']
            utc=lambda value: datetime.fromtimestamp(value,timezone.utc).isoformat()
            lines += [f'm{i},League,A,B,{utc(start+i*86400)},{utc(start+i*86400+7200)},{i%3},1,test-fixture' for i in range(300)]
            self.assertEqual(lab.import_results('\n'.join(lines))['imported'],300)
            evaluation=lab.evaluate_history()
            self.assertEqual(evaluation['partitions']['holdout']['events'],60)
            self.assertEqual(evaluation['partitions']['validation']['events'],60)
            self.assertEqual(evaluation['backtest']['events_with_prices'],0)
            self.assertFalse(evaluation['backtest']['edge_proven'])
            for prediction in evaluation['predictions']:
                self.assertLess(prediction['inputs']['last_result_available'],prediction['start'])
            second=lab.evaluate_history()
            self.assertTrue(second['frozen'])
            self.assertEqual(second['dataset_hash'],evaluation['dataset_hash'])

    def test_future_result_cannot_change_prediction(self):
        now=time.time()
        rows=[{'id':str(i),'league':'League','home':'A','away':'B','start':now-(i+1)*86400,
               'available_at':now-(i+1)*86400+7200,'home_goals':2 if i%2 else 1,'away_goals':1,'source':'test'} for i in range(100)]
        original=models.football_probabilities('A','B',rows,now)
        future={'id':'future','league':'League','home':'A','away':'B','start':now-1000,
                'available_at':now+1,'home_goals':30,'away_goals':0,'source':'test'}
        altered=models.football_probabilities('A','B',rows+[future],now)
        self.assertEqual(original,altered)
        self.assertAlmostEqual(sum(original['probabilities'].values()),1)


class SettingsSecurityTests(unittest.TestCase):
    def test_second_worker_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,'worker.lock')
            with process_lock.acquire(path):
                with self.assertRaises(RuntimeError):
                    with process_lock.acquire(path):
                        self.fail('Second worker acquired lock')
            with process_lock.acquire(path):
                pass
    @unittest.skipUnless(os.name=='nt','DPAPI is Windows-specific')
    def test_dpapi_roundtrip(self):
        cipher=secrets.encrypt('test-secret-123')
        self.assertNotIn('test-secret',cipher)
        self.assertEqual(secrets.decrypt(cipher),'test-secret-123')

    @unittest.skipUnless(os.name=='nt','DPAPI is Windows-specific')
    def test_clear_key_removes_managed_environment_value(self):
        with (tempfile.TemporaryDirectory() as tmp,
              patch.object(settings,'SETTINGS_PATH',os.path.join(tmp,'settings.json')),
              patch.dict(os.environ,{},clear=False),patch.object(settings,'_managed_env',{}),patch.object(settings,'_original_env',{})):
            os.environ.pop('ODDS_API_KEY',None)
            result=settings.save({'odds_api_key':'test-private-api-key'})
            self.assertEqual(os.environ['ODDS_API_KEY'],'test-private-api-key')
            self.assertNotIn('test-private-api-key',json.dumps(result))
            with open(settings.SETTINGS_PATH) as f:
                self.assertNotIn('test-private-api-key',f.read())
            settings.save({'clear_odds_api_key':True})
            self.assertNotIn('ODDS_API_KEY',os.environ)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=database.PATH
        database.PATH=os.path.join(self.tmp.name,'api.sqlite3')
        database.initialize()
        from app import app
        self.client=app.test_client()
        with self.client.session_transaction() as session:
            session['user']='test-user'
            session['csrf']='fixed-test-csrf'
        self.headers={'X-CSRF-Token':'fixed-test-csrf'}
        intelligence._last_scan.clear()

    def tearDown(self):
        database.PATH=self.old
        self.tmp.cleanup()

    def test_dashboard_and_mutation_require_csrf(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.post('/api/terminal/deposit',json={'mode':'DEMO','amount':100}).status_code,403)
        self.assertEqual(self.client.post('/api/terminal/deposit',json={'mode':'DEMO','amount':100},headers=self.headers).status_code,200)

    def test_complete_paper_flow_via_http(self):
        self.client.post('/api/terminal/deposit',json={'mode':'DEMO','amount':1000},headers=self.headers)
        self.assertEqual(self.client.post('/api/terminal/scan',json={'mode':'DEMO'},headers=self.headers).status_code,200)
        overview=self.client.get('/api/terminal/overview?mode=DEMO').json
        decision=next(o for o in overview['opportunities'] if o['action']=='BET')
        placed=self.client.post('/api/terminal/bets',json={'mode':'DEMO','decision_id':decision['id'],'idempotency_key':'http-test-unique'},headers=self.headers)
        self.assertEqual(placed.status_code,200)
        detail=self.client.get(f"/api/terminal/decisions/{decision['id']}?mode=DEMO").json
        self.assertEqual(detail['recorded_decision']['action'],'BET')
        self.assertEqual(detail['decision']['action'],'PASS')
        export=self.client.get('/api/terminal/history/export?mode=DEMO')
        self.assertEqual(export.status_code,200)
        self.assertIn(b'http-test',placed.data)
        self.assertIn(b'DEMO',export.data)
        self.assertEqual(self.client.get('/api/terminal/overview?mode=REAL').json['metrics']['bets'],0)

    def test_invalid_inputs_and_rebinding_are_rejected(self):
        self.assertEqual(self.client.post('/api/terminal/deposit',json={'mode':'DEMO','amount':-1},headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/api/terminal/overview?mode=INVALID').status_code,400)
        self.assertEqual(self.client.get('/',headers={'Host':'attacker.example'}).status_code,400)
        self.assertEqual(self.client.post('/api/backtest',json={},headers=self.headers).status_code,410)

    def test_authentication_required(self):
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get('/api/terminal/overview').status_code,401)
