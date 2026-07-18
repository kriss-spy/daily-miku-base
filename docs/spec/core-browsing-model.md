# Daily Miku v2 Core Browsing Model

Decision for [Prototype the core browsing experience](https://github.com/kriss-spy/daily-miku-base/issues/12), confirmed 2026-07-18.

## Direction

V2 uses the prototype's **Editorial Date Rail** direction. The Daily Slot page is artwork-first, with a narrow chronological rail and an editorial information panel. The archive uses a spacious visual grid that keeps empty dates and conflicts legible rather than presenting only a gallery of successful selections.

This document preserves the prototype's information hierarchy and interaction model, not its throwaway implementation or placeholder artwork.

## Principles

- The selected artwork is the primary visual object, but the Selection Day remains immediately visible.
- Chronology is always available without turning the page into a conventional dashboard or date-picker interface.
- `empty` and `conflict` are designed Daily Slot states, not generic error pages.
- Metadata supports the artwork instead of competing with it.
- Desktop and mobile use the same hierarchy. Mobile reflows the composition rather than substituting a separate experience.
- The server-rendered page remains complete without JavaScript. Enhancement may improve navigation and transitions but cannot hide content or state.

## Daily Slot Page

The homepage and dated route share one Daily Slot composition:

1. A narrow date rail identifies Daily Miku and exposes nearby calendar dates.
2. A large media stage presents the selected image or the slot-state treatment.
3. An editorial panel identifies the date, state, title, description, source, Raindrop ID, and recording context.
4. Previous-day and next-day links provide deterministic calendar navigation.

The homepage renders today's Slot directly. `/today` redirects to it as specified by the HTTP contract. A dated route uses the same composition and does not visually downgrade historical selections.

The date rail is a local chronological aid, not a list of only populated dates. It includes nearby empty and conflicting dates so movement through the calendar remains truthful. The current date receives the strongest marker. The rail may progressively enhance navigation, but every date remains a normal link.

## Slot States

### Selected

One controlled image occupies the media stage. The editorial panel leads with the title and a concise description, followed by source attribution, Raindrop ID, recording method, and first-observed context. The source link is secondary to calendar navigation.

### Empty

The media stage becomes a deliberate open-frame treatment with the Selection Day still visible. The editorial panel states that nothing was selected and explains that the date is retained rather than filled with another day's artwork. Metadata that does not exist is omitted.

### Conflict

The media stage shows a divided or paired treatment without promoting either candidate as the selected artwork. The editorial panel states that multiple Daily Mikus occupy the Slot and lists every candidate's title and Raindrop ID for identification. Image delivery and email remain blocked as defined by their contracts.

Conflict presentation must not resemble a supported multi-image gallery. Its visual language communicates an unresolved interruption in the chronology.

## Archive

The archive is an editorial grid of non-empty Daily Slots ordered newest-first, with explicit calendar context around it. Cards lead with artwork and show Selection Day and title. Conflict cards use a distinct divided treatment and identify the unresolved state.

Empty dates are not inserted as one card per gap into the unbounded paginated archive because that would overwhelm browsing. Instead:

- The archive heading summarizes selected, empty, and conflict counts for the active period where available.
- Month or bounded-range views preserve empty dates with quiet open-frame cells.
- Nearby-date navigation and calendar ranges always retain every date.

This reconciles the archive API's non-empty pagination with the range API's faithful calendar representation.

## Responsive Behavior

At wide widths, the date rail, media stage, and editorial panel form three vertical regions. The media stage receives the largest share of the viewport.

At narrow widths:

- The date rail remains a slim vertical anchor rather than becoming a large calendar header.
- The media stage appears first beside the rail.
- The editorial panel flows below the media stage while remaining aligned to the content column.
- Previous and next controls remain reachable after the Slot details.
- Archive cards collapse to one column; medium widths may use two columns.

The layout must work from 320 CSS pixels upward without horizontal page scrolling. Artwork uses intrinsic dimensions and `object-fit` behavior that avoids cropping when the full work can reasonably be shown.

## Visual Language

The baseline uses an editorial rather than application-dashboard language:

- Strong display typography for dates and titles, paired with restrained monospaced utility text.
- Warm neutral page surfaces, dark ink, Miku turquoise, and a small coral accent for current-date and conflict emphasis.
- Fine rules and generous whitespace instead of nested cards and elevated panels.
- Motion, when enabled, is brief and supports chronological movement. Reduced-motion preferences remove it.

Typography and color tokens must be implemented as local assets or resilient system fallbacks. The production page must not depend on a third-party font request.

## Accessibility And Semantics

- Date navigation is labelled navigation containing real links with a distinct current-date indication.
- Slot state is stated in text and never conveyed by color or composition alone.
- Candidate lists in a conflict are semantic lists.
- Images use meaningful alt text derived from authoritative content; decorative state treatments use no redundant announcement.
- Focus order follows date navigation, artwork, details, source, then previous/next navigation.
- Text and controls meet WCAG AA contrast and target-size expectations.

## Advanced Visuals

The accepted model is the reliable baseline. A later roadmap phase may prototype 3D or depth-based chronological scrolling, but that work must preserve normal links, the three Slot states, and a non-3D archive path. No 3D dependency or interaction is part of the core release.

## Prototype Outcome

Three responsive models were reviewed: Editorial Date Rail, Calendar Workspace, and Chronological Zine. Editorial Date Rail was selected because it gives the artwork the strongest presence while retaining direct chronology. The throwaway prototype was removed after this decision was captured.
