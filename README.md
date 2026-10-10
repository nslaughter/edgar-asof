# edgar-asof

What a company reported to the SEC, as it was known at any past time.

**Status:** Not yet released. The first release will read the SEC's company
facts and join each value to the acceptance time of the filing that reported
it. The decision to build this library is recorded in
[edgar-data-pipeline's decision 0009](https://github.com/nslaughter/edgar-data-pipeline/blob/main/docs/decisions/0009-read-edgar-through-a-public-point-in-time-library.md).

## What it will do

- **Keep each value in two times:** the period it describes, and when the
  filing that reported it was accepted.
- **Answer "as of T":** for a concept and a period, the value known at T, and
  the values that later filings reported for it.
- **Keep acceptance times as EDGAR gives them.** Turning them into instants,
  including the time zone a filing's header uses, is a separate step you can
  replace.
- **Fetch within the SEC's rules for automated access,** with a user agent
  you supply, a rate limit, and a cache that stores each response once and
  overwrites nothing.

Reading and parsing filing documents in general is out of scope;
[edgartools](https://github.com/dgunning/edgartools) does that well.

## EDGAR data

Data read by this library comes from the U.S. Securities and Exchange
Commission's EDGAR system. This is an independent project, not affiliated
with or endorsed by the SEC.

## License

[MIT](LICENSE).
