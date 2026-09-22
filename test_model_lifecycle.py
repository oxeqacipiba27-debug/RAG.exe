# test_model_lifecycle.py
import sys
import subprocess
import server_manager

def test_lifecycle():
    print('[1/5] Проверка исходного состояния памяти GPU...')
    initial = server_manager.get_loaded_models()
    print(f'     Текущие модели в памяти: {initial}')

    print('[2/5] Вызов ensure_autonomous_stack()...')
    ok, msg = server_manager.ensure_autonomous_stack()
    assert ok, f'ensure_autonomous_stack failed: {msg}'
    print(f'     [OK] Стек поднят: {msg}')

    print('[3/5] Проверка загруженных моделей в памяти GPU...')
    loaded = server_manager.get_loaded_models()
    print(f'     Загруженные модели: {loaded}')
    assert 'qwen2.5-14b-instruct-1m' in loaded, 'LLM model not loaded in GPU'
    assert 'text-embedding-nomic-embed-text-v1.5' in loaded, 'Embedding model not loaded in GPU'
    print('     [OK] Обе модели (LLM + Embeddings) успешно загружены!')

    print('[4/5] Вызов unload_all_models()...')
    ok_unl, msg_unl = server_manager.unload_all_models()
    assert ok_unl, f'unload_all_models failed: {msg_unl}'
    print(f'     [OK] Выгрузка выполнена: {msg_unl}')

    print('[5/5] Проверка освобождения памяти GPU...')
    final_loaded = server_manager.get_loaded_models()
    print(f'     Модели после выгрузки: {final_loaded}')
    assert len(final_loaded) == 0, f'Models still in memory: {final_loaded}'
    print('     [OK] Память GPU полностью освобождена (0 моделей в памяти)!')

    print('\n========================================')
    print(' ВСЕ ТЕСТЫ ЖИЗНЕННОГО ЦИКЛА ПРОЙДЕНЫ УСПЕШНО!')
    print('========================================')

if __name__ == '__main__':
    test_lifecycle()
