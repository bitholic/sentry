import {browserHistory} from 'react-router';
import PropTypes from 'prop-types';
import React from 'react';
import {css} from '@emotion/core';

import {t} from 'app/locale';
import parseLinkHeader from 'app/utils/parseLinkHeader';
import {callIfFunction} from 'app/utils/callIfFunction';
import {Query} from 'history';

const streamCss = css`
  margin: 20px 0 0 0;

  .icon-arrow-right,
  .icon-arrow-left {
    font-size: 20px !important;
  }
`;

const defaultProps = {
  onCursor: (cursor: string, path: string, query: Query, _direction: number) => {
    browserHistory.push({
      pathname: path,
      query: {...query, cursor},
    });
  },
  className: streamCss,
};

type DefaultProps = Readonly<typeof defaultProps>;

type Props = {
  pageLinks: string | null | undefined;
  to?: string;
} & Partial<DefaultProps>;

export default class Pagination extends React.Component<Props> {
  static propTypes = {
    pageLinks: PropTypes.string,
    to: PropTypes.string,
    onCursor: PropTypes.func,
    className: PropTypes.string,
  };

  static contextTypes = {
    location: PropTypes.object,
  };

  static defaultProps = defaultProps;

  render() {
    const {className, onCursor, pageLinks} = this.props;
    if (!pageLinks) {
      return null;
    }

    const location = this.context.location;
    const path = this.props.to || location.pathname;
    const query = location.query;

    const links = parseLinkHeader(pageLinks);

    let previousPageClassName = 'btn btn-default btn-lg prev';
    if (links.previous.results === false) {
      previousPageClassName += ' disabled';
    }

    let nextPageClassName = 'btn btn-default btn-lg next';
    if (links.next.results === false) {
      nextPageClassName += ' disabled';
    }

    return (
      <div className={'clearfix' + (className ? ` ${className}` : '')}>
        <div className="btn-group pull-right">
          <a
            onClick={() => {
              callIfFunction(onCursor, links.previous.cursor, path, query, -1);
            }}
            className={previousPageClassName}
          >
            <span title={t('Previous')} className="icon-arrow-left" />
          </a>
          <a
            onClick={() => {
              callIfFunction(onCursor, links.next.cursor, path, query, 1);
            }}
            className={nextPageClassName}
          >
            <span title={t('Next')} className="icon-arrow-right" />
          </a>
        </div>
      </div>
    );
  }
}
