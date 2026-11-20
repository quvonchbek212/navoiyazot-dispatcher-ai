"""LLM receives aggregates only and cannot change deterministic scores or ETA."""
import json


async def explain(report, lang='uz'):
    from config import DEFAULT_NUM_CTX
    from ollama_client import ask_llm
    facts = {'status': report['status'], 'summary': report['summary'], 'method': report['method']}
    prompt = ('O‘zbek tilida dispetcherga 3 qisqa jumla yozing. Faqat berilgan hisobni tushuntiring. '
              'Yangi ball, ETA, sabab, ehtimol yoki huquqiy qoida o‘ylab topmang. '
              'Ma’lumot cheklovlarini ayting. Bu hisobot umumiy haydovchi reytingi emas. Faktlar:\n'
              + json.dumps(facts, ensure_ascii=False, default=str))
    answer = await ask_llm(prompt, {'options': {'temperature': .1, 'num_predict': 300,
                                               'num_ctx': DEFAULT_NUM_CTX}, 'think': False})
    if answer and answer.strip():
        report['analysis'] = {'text': answer.strip(), 'source': 'llm'}
