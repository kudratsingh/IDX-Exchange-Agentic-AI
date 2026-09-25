# Glossary (own words; a source for the document answers, WO-012)

Each `##` heading below is one entry in the document index. The definitions match what
our tools compute (WO-008 for the market figures); where a reference document uses
another name for the same idea, the entry says so.

## days on market (DOM)

Days on market, often shortened to DOM, is how many days a home was offered for sale
before it went under contract or left the market. Both of our tables carry a
`DaysOnMarket` value that arrives with the data feed; we do not work it out ourselves.
The market tool reports the median of that stored value over the sales in its window.
A value worked out from the listing and contract dates differs from the stored one on
many sold rows (schema notes section 7), so we always use the stored value. The market
card describes the median with a band: under 15 days is very low, 15 to under 30 is
low, 30 to under 60 is average, and 60 or more is high. A sale with no stored value is
left out of this median only.

## sale-to-list ratio (also list-to-close, close-to-list)

The sale-to-list ratio compares what a home sold for with what the seller was last
asking. Some people call the same measure the list-to-close or close-to-list ratio; it
is the same arithmetic under another name. For each closed sale we divide `ClosePrice`
by `ListPrice`, the final asking price when the listing ended (not
`OriginalListPrice`, the first asking price). The market tool then takes the median of
those per-sale ratios over the window and rounds it half to even at 3 decimals. It
reads the result in plain words: 1.032 is "3% over asking", 1.000 is "at asking", and
0.980 is "2% under asking". Sales with a close price or a list price under $25,000 are
treated as data errors and left out.

## price per square foot

Price per square foot is a sale's `ClosePrice` divided by its `LivingArea` in square
feet. The market tool reports the median over the window's sales, in whole dollars. A
sale with a living area under 200 square feet, or none, is left out of this median
only, since such an area is almost always a data error.

## six-month window

Market figures use the six months of sales up to the sold as-of date unless the user
asks for another period. The window counts back from the data's as-of date, never from
today: with a sold as-of date of 2026-09-17, six months runs from 2026-03-18 to
2026-09-17. The sold data covers exactly that span, so a longer window falls back to
all of it and the reply says so.

## as-of dates

The data has two as-of dates, and every time window counts back from them. The sold
as-of date is the latest valid `CloseDate` in the sold table (2026-09-17 in the current
data, ignoring a few rows dated after the active as-of date). The active as-of date is
the latest `ModificationTimestamp` in the active table (2026-09-18). Every market
result carries both dates.
