FORGE ?= forge
OPENZEPPELIN_CONTRACTS_VERSION := v5.6.1

.PHONY: all deps build test clean fixtures

all: build fixtures

deps:
	@test -f lib/openzeppelin-contracts/package.json || \
		$(FORGE) install OpenZeppelin/openzeppelin-contracts@$(OPENZEPPELIN_CONTRACTS_VERSION) --no-git --shallow
	@python3 -c "import json; version=json.load(open('lib/openzeppelin-contracts/package.json'))['version']; assert version == '$(OPENZEPPELIN_CONTRACTS_VERSION)'[1:], f'openzeppelin-contracts version mismatch: {version}'"

build: deps
	$(FORGE) build --offline
	@mkdir -p artifacts
	@cp out/XcashVaultSlotTemplate.sol/XcashVaultSlotTemplate.json artifacts/XcashVaultSlotTemplate.json
	@python3 -c "import json; d=json.load(open('artifacts/XcashVaultSlotTemplate.json')); print(d['bytecode']['object'])" > artifacts/XcashVaultSlotTemplate.bin
	@python3 -c "import json; d=json.load(open('artifacts/XcashVaultSlotTemplate.json')); print(json.dumps(d['abi'], indent=2, ensure_ascii=False))" > artifacts/XcashVaultSlotTemplate.abi.json
	@cp out/XcashVaultSlotFactory.sol/XcashVaultSlotFactory.json artifacts/XcashVaultSlotFactory.json
	@python3 -c "import json; d=json.load(open('artifacts/XcashVaultSlotFactory.json')); print(d['bytecode']['object'])" > artifacts/XcashVaultSlotFactory.bin
	@python3 -c "import json; d=json.load(open('artifacts/XcashVaultSlotFactory.json')); print(json.dumps(d['abi'], indent=2, ensure_ascii=False))" > artifacts/XcashVaultSlotFactory.abi.json

test: deps
	$(FORGE) test --offline -vvv

fixtures: deps
	@mkdir -p ../tests/fixtures
	$(FORGE) script scripts/DumpXcashVaultSlotFixtures.s.sol --tc DumpXcashVaultSlotFixtures --offline

clean:
	rm -rf out/ cache/
