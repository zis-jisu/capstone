import unittest
from src.demo_frontend import _merge_person_profiles


class PersonProfileTests(unittest.TestCase):
    def test_canonical_contacts_fill_mock_person_without_changing_identity(self):
        result = _merge_person_profiles(
            [{'person_id': 'U1', 'name': '김지수', 'team': 'old'}],
            [{'person_id': 'U1', 'team': 'Marketing', 'email': 'test@example.com', 'phone_number': '010-0000-0000'}])
        self.assertEqual(result[0]['name'], '김지수')
        self.assertEqual(result[0]['team'], 'Marketing')
        self.assertEqual(result[0]['email'], 'test@example.com')
        self.assertEqual(result[0]['phone_number'], '010-0000-0000')

    def test_no_unrelated_people_added(self):
        self.assertEqual(_merge_person_profiles([{'person_id': 'U1'}], [{'person_id': 'U2', 'email': 'other@example.com'}]), [{'person_id': 'U1'}])

    def test_cleared_canonical_contact_is_not_replaced_with_stale_value(self):
        self.assertIsNone(_merge_person_profiles([{'person_id': 'U1', 'email': 'old@example.com'}], [{'person_id': 'U1', 'email': None}])[0]['email'])
