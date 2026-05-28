all:
	$(MAKE) -C src all

clean:
	$(MAKE) -C src clean

re:
	$(MAKE) -C src re

.DEFAULT_GOAL := all
.PHONY: all clean re