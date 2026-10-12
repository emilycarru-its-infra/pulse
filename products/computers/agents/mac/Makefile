# Managed Presence Beacon: build the app bundle (agent, app and helper) and its pkg.
#
#   make              unsigned app bundle in build/root
#   make pkg          unsigned pkg in build/
#   make sign pkg     signed, with SIGNING_IDENTITY_APP / SIGNING_IDENTITY_PKG set
#   make notarize     with NOTARIZATION_PROFILE set
#
# Signing happens in the internal build; nothing here carries an identity. A .env file
# beside this Makefile can set the variables.

-include .env
export

VERSION := $(or $(VERSION),$(shell date '+%Y.%m.%d.%H%M'))
# 2026.10.12.1342 shows as 2026.10.12 (1342) in Finder and the About box.
MARKETING_VERSION := $(shell echo $(VERSION) | sed 's/\.[^.]*$$//')
BUILD_NUMBER := $(shell echo $(VERSION) | sed 's/.*\.//')

BUILD_DIR = build
ROOT = $(BUILD_DIR)/root
APP = $(ROOT)/Applications/Utilities/Managed Presence Beacon.app
SWIFT_OUT = $(shell swift build -c release --arch arm64 --arch x86_64 --show-bin-path 2>/dev/null)
ICON_DIR = resources/ManagedPresenceBeacon.icon
ICON_NAME = ManagedPresenceBeacon
ACTOOL_OUT = $(BUILD_DIR)/actool
PKG_ID = com.github.managedpulse
PKG = $(BUILD_DIR)/ManagedPresenceBeacon-$(VERSION).pkg

.PHONY: all swift app sign pkg notarize test clean

all: app

test:
	swift test

swift:
	@mkdir -p $(BUILD_DIR)
	@cp Sources/core/BuildVersion.swift $(BUILD_DIR)/BuildVersion.swift.orig
	@sed -i '' 's/value = ".*"/value = "$(VERSION)"/' Sources/core/BuildVersion.swift
	swift build -c release --arch arm64 --arch x86_64; status=$$?; \
		cp $(BUILD_DIR)/BuildVersion.swift.orig Sources/core/BuildVersion.swift; exit $$status

$(ACTOOL_OUT)/Assets.car: $(ICON_DIR)/icon.json
	@mkdir -p $(ACTOOL_OUT)
	xcrun actool --compile $(ACTOOL_OUT) --platform macosx --minimum-deployment-target 14.0 \
		--app-icon $(ICON_NAME) --output-partial-info-plist $(ACTOOL_OUT)/partial-info.plist \
		--warnings --errors $(ICON_DIR) > /dev/null

app: swift $(ACTOOL_OUT)/Assets.car
	@rm -rf "$(APP)"
	@mkdir -p "$(APP)/Contents/MacOS" "$(APP)/Contents/Resources" "$(APP)/Contents/Library/LaunchDaemons" \
		$(ROOT)/Library/LaunchDaemons
	cp $(SWIFT_OUT)/ManagedPresenceBeaconApp "$(APP)/Contents/MacOS/ManagedPresenceBeacon"
	cp $(SWIFT_OUT)/managedpulse "$(APP)/Contents/MacOS/managedpulse"
	cp $(SWIFT_OUT)/ManagedPresenceBeaconHelper "$(APP)/Contents/MacOS/ManagedPresenceBeaconHelper"
	sed -e 's/{{MARKETING_VERSION}}/$(MARKETING_VERSION)/g' -e 's/{{BUILD_NUMBER}}/$(BUILD_NUMBER)/g' \
		packaging/resources/Info.plist.template > "$(APP)/Contents/Info.plist"
	cp $(ACTOOL_OUT)/Assets.car $(ACTOOL_OUT)/$(ICON_NAME).icns "$(APP)/Contents/Resources/"
	cp packaging/LaunchDaemons/com.github.managedpulse.helper.plist "$(APP)/Contents/Library/LaunchDaemons/"
	cp packaging/LaunchDaemons/com.github.managedpulse.plist $(ROOT)/Library/LaunchDaemons/
	@echo "Built $(APP) $(VERSION)"

# Inside out: each binary with its own identifier, then the bundle.
sign:
	@test -n "$(SIGNING_IDENTITY_APP)" || { echo "Set SIGNING_IDENTITY_APP"; exit 1; }
	codesign --force --options runtime --timestamp --sign "$(SIGNING_IDENTITY_APP)" \
		--identifier com.github.managedpulse.cli "$(APP)/Contents/MacOS/managedpulse"
	codesign --force --options runtime --timestamp --sign "$(SIGNING_IDENTITY_APP)" \
		--identifier com.github.managedpulse.helper "$(APP)/Contents/MacOS/ManagedPresenceBeaconHelper"
	codesign --force --options runtime --timestamp --sign "$(SIGNING_IDENTITY_APP)" "$(APP)"

pkg:
	pkgbuild --analyze --root $(ROOT) $(BUILD_DIR)/component.plist
	/usr/libexec/PlistBuddy -c "Set :0:BundleIsRelocatable false" $(BUILD_DIR)/component.plist
	/usr/libexec/PlistBuddy -c "Set :0:BundleIsVersionChecked false" $(BUILD_DIR)/component.plist
	pkgbuild --root $(ROOT) --component-plist $(BUILD_DIR)/component.plist --identifier $(PKG_ID) \
		--version $(VERSION) --scripts packaging/scripts $(PKG)
	@if [ -n "$(SIGNING_IDENTITY_PKG)" ]; then \
		productsign --sign "$(SIGNING_IDENTITY_PKG)" --timestamp $(PKG) $(PKG).signed && mv $(PKG).signed $(PKG); \
	fi
	@echo "Built $(PKG)"

notarize:
	@test -n "$(NOTARIZATION_PROFILE)" || { echo "Set NOTARIZATION_PROFILE"; exit 1; }
	xcrun notarytool submit $(PKG) --keychain-profile "$(NOTARIZATION_PROFILE)" --wait
	xcrun stapler staple $(PKG)

clean:
	rm -rf $(BUILD_DIR) .build
