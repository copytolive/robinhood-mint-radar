import unittest
from radar.scanner import word_to_address,data_word

class DecodeTests(unittest.TestCase):
    def test_topic_address(self):
        t='0x'+'0'*24+'1234567890abcdef1234567890abcdef12345678'
        self.assertEqual(word_to_address(t),'0x1234567890abcdef1234567890abcdef12345678')
    def test_data_word(self):
        d='0x'+('0'*63)+'a'
        self.assertEqual(data_word(d,0),10)

if __name__=='__main__': unittest.main()
