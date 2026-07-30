# Daily Miku Domain Glossary

## Daily Miku

A Raindrop bookmark selected for one Daily Slot by carrying exactly one valid Dated Selection Tag. The bookmark may be new or may have existed before selection.

## Selection Day

The calendar date encoded in a Daily Miku's Dated Selection Tag. It identifies the Daily Slot and does not claim when the tag was added; the bookmark's creation and update timestamps do not affect it.

## Dated Selection Tag

The canonical Raindrop tag `daily-miku-YYYY-MM-DD`, with a strict, zero-padded Gregorian date. It is the authoritative Selection Day; a bookmark carrying multiple Dated Selection Tags is invalid until corrected.

## Daily Slot

The publication slot for one Selection Day. A Daily Slot may contain one Daily Miku or be empty. More than one candidate is a conflict, not a gallery: the website reports the conflict and daily email delivery pauses until it is resolved.

## Email Delivery

The outcome of sending one selected Daily Miku for one Daily Slot to one configured recipient. An empty or conflicting Daily Slot cannot produce an Email Delivery.

## Selection Correction

An operator change that replaces a Daily Miku's Dated Selection Tag. It changes current publication state; Raindrop does not provide a durable history of the former tag, operator, or time of change.

## Image Withdrawal

A recorded decision that a Daily Miku's controlled image must no longer be delivered. A withdrawal is distinct from an image that is missing or temporarily unavailable.
