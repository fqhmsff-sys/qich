test:
	python3 -m unittest discover -s tests -p "test_*.py"
	PYTHONPATH=src python3 -m qich test
install:
	sh install.sh
.PHONY: test install
