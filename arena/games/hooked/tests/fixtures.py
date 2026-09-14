from pathlib import Path

NATIVE_SUBMIT = (Path(__file__).parent/'fixtures/hooked-submit.xml').read_bytes()
NATIVE_TOPN = (Path(__file__).parent/'fixtures/hooked-topn.xml').read_bytes()
NATIVE_PROXIMITY = (Path(__file__).parent/'fixtures/hooked-proximity.xml').read_bytes()
