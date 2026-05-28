DEBUG ?= 0
CC ?= cc
TARGET ?= permutator

SRC := main.c
OBJ := $(SRC:.c=.o)
OUT := ../$(TARGET)

ifeq ($(DEBUG),1)
CFLAGS ?= -O1 -g3 -std=c17 -Wall -Wextra
else
CFLAGS ?= -O3 -march=native -flto -std=c17 -Wall -Wextra
endif

LDFLAGS ?=
LDLIBS ?=

.PHONY: all clean re

all: $(OUT)

$(OUT): $(OBJ)
	$(CC) $(CFLAGS) $(LDFLAGS) $^ $(LDLIBS) -o $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJ) $(OUT)

re: clean all
