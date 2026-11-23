import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from src import core


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = core.DB_PATH
        core.DB_PATH = Path(self.temp.name) / 'test.db'

    def tearDown(self):
        core.DB_PATH = self.old_db
        self.temp.cleanup()

    def task(self, minutes=60, days=2, priority=3):
        return core.add_task({'title': 'Exercícios de grafos', 'subject': 'Algoritmos', 'deadline': (date.today() + timedelta(days=days)).isoformat(), 'minutes': minutes, 'priority': priority})

    def test_insert_and_list(self):
        added = self.task()
        self.assertEqual(core.list_tasks()[0]['id'], added['id'])

    def test_reject_invalid_data(self):
        with self.assertRaises(ValueError): self.task(minutes=0)
        with self.assertRaises(ValueError): self.task(priority=6)
        with self.assertRaises(ValueError): core.add_task({'title':'Teste','subject':'SI','deadline':'1900-01-01','minutes':30,'priority':2})

    def test_demo_end_to_end_and_approval(self):
        self.task(120)
        result = core.run_workflow({'hours_per_day': 2, 'days': 3, 'mode': 'demo'})
        self.assertTrue(result['result']['review']['approved_by_rules'])
        self.assertEqual(result['result']['status'], 'proposto')
        self.assertGreaterEqual(len(result['trace']), 4)
        plan_id = result['result']['id']
        self.assertEqual(core.approve_plan(plan_id)['status'], 'aprovado')
        self.assertEqual(core.get_plan(plan_id)['status'], 'aprovado')
        with self.assertRaises(ValueError): core.approve_plan(plan_id)

    def test_insufficient_capacity_is_visible(self):
        self.task(600, days=1)
        r = core.run_workflow({'hours_per_day': 1, 'days': 1, 'mode': 'demo'})
        self.assertGreater(r['result']['plan']['pending'][0]['minutes_unallocated'], 0)

    def test_complete_task_removed_from_planning(self):
        t = self.task()
        core.set_done(t['id'], True)
        with self.assertRaises(ValueError): core.run_workflow({'hours_per_day': 2, 'days': 3, 'mode': 'demo'})

    def test_invalid_model_order_rejected(self):
        t = self.task()
        with patch.object(core, 'ask_model', return_value={'ordered_ids': [999], 'reason': 'bad'}):
            with self.assertRaises(ValueError): core.run_workflow({'hours_per_day': 2, 'days': 3, 'mode': 'ollama'})


    def test_ollama_model_output_tips_as_string_is_normalized(self):
        self.task()
        def mock_model(system, payload, schema=None):
            if 'triagem' in system:
                return {'ordered_ids': [payload['tasks'][0]['id']], 'reason': 'Prazo próximo'}
            if 'planejador' in system:
                return {'tips': 'Reserve um tempo para revisão'}
            return {'risks': 'Possível fadiga'}
        with patch.object(core, 'ask_model', side_effect=mock_model):
            result = core.run_workflow({'hours_per_day': 2, 'days': 3, 'mode': 'ollama'})
        self.assertEqual(result['result']['plan']['tips'], ['Reserve um tempo para revisão'])
        self.assertIn('Possível fadiga', result['result']['review']['risks'])

    def test_ollama_rejects_untrusted_tip_objects(self):
        self.task()
        def mock_model(system, payload, schema=None):
            if 'triagem' in system:
                return {'ordered_ids': [payload['tasks'][0]['id']], 'reason': 'OK'}
            return {'tips': [{'unexpected': 'object'}]}
        with patch.object(core, 'ask_model', side_effect=mock_model):
            with self.assertRaisesRegex(ValueError, 'dicas de texto'):
                core.run_workflow({'hours_per_day': 2, 'days': 3, 'mode': 'ollama'})

    def test_reviewer_detects_broken_plan(self):
        t = self.task(minutes=30)
        data = {'days': [{'date': date.today().isoformat(), 'sessions': [{'task_id': t['id'], 'minutes': 300}], 'remaining': 0}], 'pending': []}
        r = core.review_agent(data, core.list_tasks(), 1, 'demo', [])
        self.assertFalse(r['approved_by_rules'])

    def test_seed_does_not_duplicate(self):
        self.assertEqual(core.seed_demo()['created'], 4)
        self.assertEqual(core.seed_demo()['created'], 0)

if __name__ == '__main__':
    unittest.main()
