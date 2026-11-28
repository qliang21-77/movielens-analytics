import re
import time
import pandas as pd
import streamlit as st
import mysql.connector
import altair as alt

st.set_page_config(page_title='MovieLens Analytics', layout='wide')
st.title('MovieLens Analytics')
st.caption('DSCI 551 | Movie Rating and Database Performance Analysis')
with st.sidebar:
    page = st.radio('Navigation', ['Database','Data Overview','Query Workload','Performance Experiments','Query Processing'])
    st.caption('Cloud database · MovieLens')

if page != 'Query Processing':
    try:
        config = st.secrets['mysql']
        host = config['host']
        user = config['user']
        password = config['password']
        database = config['database']
        port = int(config.get('port', 3306))
    except (KeyError, FileNotFoundError):
        st.error('Database configuration is missing. Please contact the app administrator.')
        st.stop()

def run(sql, params=(), schema=None):
    try:
        with mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=schema or database,
            connection_timeout=20,
            ssl_disabled=False,
            ssl_verify_cert=True,
            ssl_verify_identity=True
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return pd.DataFrame(
                    cur.fetchall(),
                    columns=cur.column_names
                )

    except Exception:
        import logging
        logging.exception("Database query failed")
        raise


def format_sql(sql):
    """Format SQL for display only; never change the executed statement."""
    # Keep quoted strings and identifiers intact, including regex patterns.
    token_pattern = r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"|`(?:``|[^`])*`|\b(?:LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|OUTER\s+JOIN|CROSS\s+JOIN|GROUP\s+BY|ORDER\s+BY|UNION\s+ALL|SELECT|FROM|JOIN|ON|WHERE|HAVING|LIMIT|UNION|WHEN|ELSE|END)\b|[(),]|\s+|[^\s(),]+?"
    tokens = re.findall(token_pattern, sql, flags=re.IGNORECASE)
    if not re.search(r'\bSELECT\b', sql, re.IGNORECASE):
        return sql
    out = ''
    depth = 0
    clauses = {}
    pending_space = False
    def newline(indent):
        return '\n' + '    ' * max(0, indent)
    for token in tokens:
        if token.isspace():
            pending_space = True
            continue
        key = ' '.join(token.upper().split())
        if key in ('SELECT','FROM','JOIN','LEFT JOIN','RIGHT JOIN','INNER JOIN','OUTER JOIN','CROSS JOIN','ON','WHERE','GROUP BY','HAVING','ORDER BY','LIMIT','UNION','UNION ALL','WHEN','ELSE','END'):
            if key in ('SELECT','FROM','GROUP BY','ORDER BY','WHERE','HAVING','LIMIT','ON') or key.endswith('JOIN'):
                clauses[depth] = key
            indent = depth + (1 if key in ('ON','WHEN','ELSE','END') else 0)
            out = out.rstrip() + (newline(indent) if out.strip() else '') + key
            if key in ('SELECT','GROUP BY','ORDER BY'):
                out += newline(depth+1)
            pending_space = False
        elif token == '(':
            if pending_space and out and not out[-1].isspace(): out += ' '
            out += token
            depth += 1
            pending_space = False
        elif token == ')':
            clauses.pop(depth, None)
            depth = max(0, depth-1)
            out = out.rstrip() + token
            pending_space = False
        elif token == ',':
            out = out.rstrip() + ','
            if clauses.get(depth) in ('SELECT','GROUP BY','ORDER BY'):
                out += newline(depth+1)
                pending_space = False
            else:
                pending_space = True
        else:
            if pending_space and out and not out[-1].isspace(): out += ' '
            out += token
            pending_space = False
    return out.strip()


def show_sql(sql):
    st.code(format_sql(sql), language='sql')

def show(sql, params=(), chart=None):
    with st.expander('View SQL'):
        show_sql(sql)
        st.write('Parameters:', params)
    df=run(sql,params)
    for c in df.columns:
        if c not in ['title','genreName','activity_range','release_year_range','table_name']:
            try:
                df[c]=pd.to_numeric(df[c])
            except (ValueError, TypeError):
                pass
    st.dataframe(df, hide_index=True, use_container_width=True)
    if chart and not df.empty:
        kind,x,y=chart
        getattr(st,kind+'_chart')(df,x=x,y=y)
    return df

TOP='''SELECT m.movieId, m.title, COUNT(r.rating) AS rating_count,
ROUND(AVG(r.rating),2) AS average_rating
FROM movies m JOIN ratings r ON m.movieId=r.movieId
GROUP BY m.movieId,m.title HAVING COUNT(r.rating)>=%s
ORDER BY average_rating DESC,rating_count DESC'''
CTE='''WITH top_movies AS (
SELECT movieId,COUNT(rating) AS rating_count,ROUND(AVG(rating),2) AS average_rating
FROM ratings GROUP BY movieId HAVING COUNT(rating)>=%s
ORDER BY average_rating DESC,rating_count DESC LIMIT %s)
SELECT tm.movieId,m.title,tm.rating_count,tm.average_rating
FROM top_movies tm JOIN movies m ON tm.movieId=m.movieId
ORDER BY tm.average_rating DESC,tm.rating_count DESC'''
GENRE='''SELECT g.genreId,g.genreName,COUNT(DISTINCT mg.movieId) AS num_movies,
COUNT(r.rating) AS num_ratings,ROUND(AVG(r.rating),2) AS avg_rating
FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId
LEFT JOIN ratings r ON mg.movieId=r.movieId GROUP BY g.genreId,g.genreName
ORDER BY num_movies DESC'''
ACTIVITY='''WITH user_activity AS (SELECT u.userId,COUNT(DISTINCT r.movieId) AS num_movies_rated
FROM users u LEFT JOIN ratings r ON u.userId=r.userId GROUP BY u.userId)
SELECT CASE WHEN num_movies_rated<50 THEN '0-49' WHEN num_movies_rated<100 THEN '50-99'
WHEN num_movies_rated<200 THEN '100-199' WHEN num_movies_rated<500 THEN '200-499'
WHEN num_movies_rated<1000 THEN '500-999' ELSE '1000+' END AS activity_range,
COUNT(*) AS num_users FROM user_activity GROUP BY activity_range ORDER BY MIN(num_movies_rated)'''
NORMAL='''WITH movie_stats AS (SELECT m.movieId,COUNT(r.rating) AS rating_count,
SUM(r.rating) AS total_rating_score,AVG(r.rating) AS movie_avg_rating
FROM movies m LEFT JOIN ratings r ON m.movieId=r.movieId GROUP BY m.movieId)
SELECT g.genreName,COUNT(ms.movieId) AS movie_count,SUM(ms.rating_count) AS total_ratings,
ROUND(AVG(ms.rating_count),2) AS avg_ratings_received_per_movie,
ROUND(SUM(ms.total_rating_score)/NULLIF(SUM(ms.rating_count),0),2) AS weighted_avg_rating,
ROUND(AVG(ms.movie_avg_rating),2) AS movie_level_avg_rating
FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId JOIN movie_stats ms ON mg.movieId=ms.movieId
GROUP BY g.genreId,g.genreName ORDER BY total_ratings DESC'''
FAVORITE='''WITH user_genre_ratings AS (SELECT r.userId,g.genreName,COUNT(*) AS favorite_count
FROM ratings r JOIN movie_genres mg ON r.movieId=mg.movieId JOIN genres g ON mg.genreId=g.genreId
WHERE r.rating >= %s GROUP BY r.userId,g.genreId,g.genreName),
ranked_genres AS (SELECT userId,genreName,favorite_count,RANK() OVER(PARTITION BY userId ORDER BY favorite_count DESC) AS genre_rank FROM user_genre_ratings)
SELECT userId,genreName,favorite_count FROM ranked_genres WHERE genre_rank=1'''

def overview():
    st.header('Data Overview')
    tables=['movies','users','ratings','genres','tags','links','movie_genres']
    df=run('SELECT '+','.join(f'(SELECT COUNT(*) FROM {t}) AS {t}' for t in tables))
    for cols, names in [(st.columns(4),tables[:4]),(st.columns(3),tables[4:])]:
        for col,t in zip(cols,names): col.metric(t.replace('_',' ').title(),f'{df.iloc[0][t]:,}')
    st.subheader('Estimated Database Size (MB)')
    show('''SELECT ROUND(SUM(data_length)/1048576,2) AS data_MB,
ROUND(SUM(index_length)/1048576,2) AS index_MB,
ROUND(SUM(data_length+index_length)/1048576,2) AS total_MB
FROM information_schema.tables WHERE table_schema=DATABASE()''')
    st.subheader('Rating Summary')
    show('SELECT COUNT(*) AS total_ratings,MIN(rating) AS min_rating,MAX(rating) AS max_rating,ROUND(AVG(rating),2) AS avg_rating,ROUND(STDDEV_POP(rating),2) AS std_rating FROM ratings')
    st.subheader('Movie Distribution by Genre')
    df=show(GENRE)
    for y in ['num_movies','num_ratings','avg_rating']: st.bar_chart(df,x='genreName',y=y,horizontal=True)
    st.caption('Movies and ratings can contribute to multiple genres.')
    st.subheader('User Rating Activity')
    df = show(ACTIVITY)
    activity_order = [
        '0-49',
        '50-99',
        '100-199',
        '200-499',
        '500-999',
        '1000+'
    ]

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X(
            'activity_range:N',
            sort=activity_order,
            title='Number of Movies Rated',
            axis=alt.Axis(labelAngle=0)
        ),
        y=alt.Y(
            'num_users:Q',
            title='Number of Users',
            scale=alt.Scale(zero=True)
        ),
        tooltip=['activity_range', 'num_users']
    ).properties(
        height=350
    )

    st.altair_chart(chart, use_container_width=True)

def database_page():
    st.header('Database')
    st.caption('Implemented schema, loading pipeline, relationships and live representative data.')
    st.subheader('Entity Relationship Diagram')

    st.image(
        'images/551_Project EER Diagram.png',
        caption='MovieLens relational database schema',
        use_container_width=True
    )
    
    tables = ['movies', 'users', 'ratings', 'genres', 'tags', 'links', 'movie_genres']
    a,b,c,d = st.tabs(['Schema Design', 'Load Dataset', 'Representative Data', 'Database Size'])
    with a:
        st.subheader('Relational Schema and Entity Relationships')
        st.markdown("""| Entity / Table | Related Table | Relationship | Description |
|---|---|---|---|
| users | ratings | One-to-many | One user can rate multiple movies, while each rating belongs to one user |
| users | tags | One-to-many | One user can create multiple tags, while each tag record belongs to one user |
| users | movies | Many-to-many | One user can rate multiple movies One movie can have ratings from multiple users One user can only rate one movie at most once. The ratings table connects the two entities, where each user could at most once rate a particular movie |
| movies | ratings | One-to-many | One movie can receive multiple ratings, while each rating belongs to one movie|
| movies | tags | One-to-many | One movie can have multiple tags, while each tag record belongs to one movie|
| movies | links | One-to-one | One movie only has one link, and each link record belongs to one movie|
| movies | genres | Many-to-many (via movie_genres) | One movie can belong to multiple genres, and one genre can be associated with multiple movies. The movie_genres junction table connects the two tables through movieId and genreId|
| movies | movie_genres | One-to-many | One movie can belong to many movie genres, and each record references one movie |
| genres | movie_genres | One-to-many | One genre can be associated with multiple movies through the movie_genres table, while each movie-genre record references one genre|
""")
        st.caption( 'The ratings and tags tables represent many-to-many '
    'relationships between users and movies, while '
    'movie_genres resolves the many-to-many relationship '
    'between movies and genres.')
        table = st.selectbox('Inspect table structure', tables)
        ddl = run(f'SHOW CREATE TABLE `{table}`')
        show_sql(str(ddl.iloc[0,1]))
        st.subheader('Live Key Constraints')
        show("""SELECT table_name, constraint_name, column_name,
        referenced_table_name, referenced_column_name
        FROM information_schema.key_column_usage
        WHERE table_schema=DATABASE()
        ORDER BY table_name,constraint_name,ordinal_position""")
    with b:
        st.subheader('Create Database and Load Dataset')
        st.caption('Reproduction examples for local MySQL. These statements are displayed only, never executed by this app. The deployed schema is configured separately.')
        show_sql('CREATE DATABASE IF NOT EXISTS project_551;\nUSE project_551;')
        st.markdown('**1. Import the four original MovieLens CSV files**')
        fields = {'movies':'movieId, title, genres', 'ratings':'userId, movieId, rating, timestamp', 'tags':'userId, movieId, tag, timestamp', 'links':'movieId, imdbId, tmdbId'}
        st.caption('Create the tables first using the schema shown in Schema Design. For a fresh load, stage ratings and tags or populate users before importing dependent rows so foreign keys remain valid.')
        for name, columns in fields.items():
            with st.expander(name + '.csv'):
                show_sql(f"""LOAD DATA LOCAL INFILE 'PATH_TO_ML_LATEST_SMALL/{name}.csv'
INTO TABLE {name}
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '"'
LINES TERMINATED BY '\\n'
IGNORE 1 LINES
({columns});""")
        st.markdown('**2. Derive unique users from ratings and tags**')
        st.caption('For a fresh import with foreign keys enabled, use staging tables as the source of this UNION before loading ratings and tags. The following illustrates the transformation in the project documentation.')
        show_sql('INSERT INTO users (userId)\nSELECT userId FROM ratings\nUNION\nSELECT userId FROM tags;')
        st.markdown('**3. Normalize movie genres**')
        st.write('Split pipe-separated genre names, remove duplicates, exclude (no genres listed), and populate the movie-to-genre bridge table.')
        split = """SELECT m.movieId, TRIM(REPLACE(SUBSTRING_INDEX(
    SUBSTRING_INDEX(m.genres, '|', n.n), '|', -1), CHAR(13), '')) AS genre
FROM movies m JOIN (
    SELECT 1 AS n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4
    UNION SELECT 5 UNION SELECT 6 UNION SELECT 7 UNION SELECT 8
    UNION SELECT 9 UNION SELECT 10
) n ON CHAR_LENGTH(m.genres)-CHAR_LENGTH(REPLACE(m.genres,'|','')) >= n.n-1"""
        show_sql('INSERT INTO genres (genreName)\nSELECT DISTINCT genre FROM (\n'+split+"\n) x WHERE genre <> '(no genres listed)';")
        show_sql('INSERT INTO movie_genres (movieId, genreId)\nSELECT DISTINCT x.movieId, g.genreId FROM (\n'+split+'\n) x JOIN genres g ON x.genre=g.genreName;')
        st.markdown('**4. Cloud deployment**')
        st.write('Export local MySQL structure and data, import the SQL dump into cloud MySQL, and connect Streamlit using server-side secrets.')
    with c:
        st.subheader('Live Representative Data')
        sample = st.selectbox('Select a table', tables)
        limit = st.slider('Sample rows', 5, 50, 10, key='db_sample_limit')
        sql = f'SELECT * FROM `{sample}` LIMIT %s'
        show_sql(sql)
        st.dataframe(run(sql,(limit,)), hide_index=True, use_container_width=True)
        st.caption('Representative sample, not a random or ordered sample.')
    with d:
        st.subheader('Live Row Counts')
        show(' UNION ALL '.join(f"SELECT '{t}' AS table_name, COUNT(*) AS row_count FROM `{t}`" for t in tables))
        st.subheader('Estimated Storage by Table (MB)')
        show("""SELECT table_name, ROUND(data_length/1048576,2) AS data_MB,
        ROUND(index_length/1048576,2) AS index_MB,
        ROUND((data_length+index_length)/1048576,2) AS total_MB
        FROM information_schema.tables WHERE table_schema=DATABASE()
        AND table_type='BASE TABLE' ORDER BY total_MB DESC""")
        st.subheader('Total Estimated Database Size (MB)')
        show("""SELECT ROUND(SUM(data_length)/1048576,2) AS data_MB,
        ROUND(SUM(index_length)/1048576,2) AS index_MB,
        ROUND(SUM(data_length+index_length)/1048576,2) AS total_MB
        FROM information_schema.tables WHERE table_schema=DATABASE()
        AND table_type='BASE TABLE'""")
        st.caption('InnoDB storage estimates include allocated data and index pages; exact row counts are queried separately.')

def queries():
    st.header('Query Workload')
    q=st.selectbox('Research Question',['Q1 — Top Rated Movies','Q2 — Average Rating by Genre','Q3 — Genre Popularity vs. Rating','Q4 — Genre and User Engagement','Q5 — Release Period vs. Rating','Q6 — Favorite Genre by User'])
    chart=None; params=()
    if q.startswith('Q1'):
        minimum=st.number_input('Minimum ratings',1,100000,50); n=st.slider('Top N',1,100,10)
        sql=TOP+' LIMIT %s'; params=(minimum,n)
    elif q.startswith('Q2'):
        minimum=st.number_input('Minimum ratings per genre',1,100000,50)
        sql='''SELECT g.genreName,COUNT(r.rating) AS rating_count,ROUND(AVG(r.rating),2) AS average_rating FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId JOIN ratings r ON mg.movieId=r.movieId GROUP BY g.genreId,g.genreName HAVING COUNT(r.rating)>=%s ORDER BY average_rating DESC,rating_count DESC'''; params=(minimum,); chart=('bar','genreName','average_rating')
    elif q.startswith('Q3'):
        mode=st.radio('Popularity measure',['Before normalization','After normalization'])
        if mode=='Before normalization':
            sql='''SELECT g.genreName,COUNT(DISTINCT mg.movieId) AS movie_count,COUNT(r.rating) AS rating_count,ROUND(AVG(r.rating),2) AS average_rating FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId JOIN ratings r ON mg.movieId=r.movieId GROUP BY g.genreId,g.genreName ORDER BY rating_count DESC'''; chart=('scatter','rating_count','average_rating')
        else:
            sql=NORMAL; chart=('scatter','avg_ratings_received_per_movie','movie_level_avg_rating')
    elif q.startswith('Q4'):
        genres=run('SELECT genreName FROM genres ORDER BY genreName')['genreName'].tolist()
        genre=st.selectbox('Genre',['All genres']+genres)
        sql='''SELECT g.genreName,COUNT(r.rating) AS rating_count,COUNT(DISTINCT r.userId) AS unique_users,ROUND(COUNT(DISTINCT r.userId)*100.0/(SELECT COUNT(*) FROM users),2) AS user_participation_pct FROM genres g JOIN movie_genres mg ON g.genreId=mg.genreId JOIN ratings r ON mg.movieId=r.movieId'''
        if genre!='All genres': sql+=' WHERE g.genreName=%s'; params=(genre,)
        sql+=' GROUP BY g.genreId,g.genreName ORDER BY rating_count DESC'; chart=('bar','genreName','user_participation_pct')
    elif q.startswith('Q5'):
        lo,hi=st.slider('Release decades',1900,2020,(1900,2010),10)
        sql='''WITH movie_stats AS (SELECT m.movieId,FLOOR(CAST(SUBSTRING(m.title,-5,4) AS UNSIGNED)/10)*10 AS decade,COUNT(r.rating) AS rating_count,AVG(r.rating) AS movie_avg_rating FROM movies m JOIN ratings r ON m.movieId=r.movieId WHERE m.title REGEXP '[(][0-9]{4}[)]$' GROUP BY m.movieId,m.title) SELECT CONCAT(decade,'-',decade+9) AS release_year_range,COUNT(*) AS movie_count,SUM(rating_count) AS total_ratings,ROUND(AVG(movie_avg_rating),2) AS movie_level_avg_rating FROM movie_stats WHERE decade BETWEEN %s AND %s GROUP BY decade ORDER BY decade'''; params=(lo,hi); chart=('line','release_year_range','movie_level_avg_rating')
    else:
        threshold=st.slider('Minimum rating to count as a favorite',0.5,5.0,4.0,0.5)
        users=run('SELECT userId FROM users ORDER BY userId')['userId'].tolist()
        uid=st.selectbox('User',['All users']+users)
        sql=FAVORITE; params=(threshold,)
        if uid!='All users': sql+=' AND userId=%s'; params+=(uid,)
        sql+=' ORDER BY favorite_count DESC,userId,genreName'
        if uid=='All users': sql+=' LIMIT 10'
        st.caption('Ties are retained by RANK; the all-users view displays the top 10 rows.')
    if st.button('Run Query',type='primary'):
        show(sql,params,chart)


def experiments():
    st.header('Performance Experiments')
    st.caption('Historical measurements from the report, with live SQL demonstrations using the configured cloud database.')
    st.markdown("""
    **E.1 Indexing**

    Evaluates how different composite index designs affect access to the ratings table and the execution time of a query identifying the highest-rated movies.

    **E.2 Sorting and Join**

    Compares full sorting, Top-N sorting, and early aggregation to examine how reducing intermediate results affects query processing.

    **E.3 Index-Provided Ordering**

    Compares explicit sorting with index-provided ordering to examine how a composite index on `(rating, movieId)` can eliminate a separate sorting operation.
    """)
    
    a, b, c, d, e, f = st.tabs([
        'Indexing',
        'E.1 Live Query',
        'Sorting and Join',
        'E.2 Live Query Lab',
        'Index-Provided Ordering',
        'E.3 Live Query'
    ])

    with a:
        st.subheader('E.1 Indexing Experiment')
        df = pd.DataFrame({
            'Index configuration': [
                'movieId',
                'movieId, rating',
                'rating, movieId'
            ],
            'Execution time (ms)': [214, 112, 195]
        })
        st.dataframe(df, hide_index=True)
        st.bar_chart(df, x='Index configuration', y='Execution time (ms)')
        st.metric('Observed reduction', '47.66%')
        st.caption(
            'The composite index (movieId, rating) changed the ratings '
            'access from a regular index lookup to a covering index lookup. '
            'The reversed index was less effective because the query joins '
            'on movieId rather than filtering on rating.'
        )

    with b:
        st.subheader('E.1 Live Query: Indexing')
        st.write('Compare the same query using three existing indexes. FORCE INDEX restricts index selection for ratings; MySQL still chooses the execution plan. No indexes are created or dropped.')
        st.caption('Live forced-index tests are not identical to the historical experiments. Timings can vary with caching and server load.')
        configs = [('Single-column index', 'movieId', 214),
                   ('Composite index', 'idx_ratings_movie_rating', 112),
                   ('Reversed composite index', 'idx_ratings_rating_movie', 195)]
        run_all = st.button('Run All Experiments', key='e1_all', type='primary')
        if 'e1_results' not in st.session_state:
            st.session_state['e1_results'] = {}
        if run_all:
            st.session_state['e1_results'] = {}
        for i, (label, index, historical) in enumerate(configs, 1):
            st.subheader(f'Experiment {i}: {label}')
            st.caption(f'Index: {index} | Historical execution time: {historical} ms')
            sql = TOP.replace('JOIN ratings r ON', f'JOIN ratings r FORCE INDEX (`{index}`) ON').replace('%s', '50') + ' LIMIT 10'
            show_sql(sql)
            clicked = st.button(f'Run Experiment {i}', key=f'e1_run_{i}')
            if clicked or run_all:
                st.session_state['e1_results'].pop(index, None)
                try:
                    with st.spinner('Running experiment...'):
                        plan = run('EXPLAIN ANALYZE ' + sql, schema=database)
                        plan_text = '\n'.join(str(x) for x in plan.iloc[:, 0])
                        match = re.search(r'actual time=[\d.]+\.\.([\d.]+)', plan_text)
                        results = run(sql, schema=database)
                        st.session_state['e1_results'][index] = (plan_text, float(match.group(1)) if match else None, results)
                except mysql.connector.Error:
                    st.error('Experiment failed. Check the database connection and index availability.')
            saved = st.session_state['e1_results'].get(index)
            if saved is not None:
                plan_text, elapsed, results = saved
                if elapsed is not None:
                    st.metric('Root iterator completion time', f'{elapsed:g} ms')
                st.markdown('**Execution Plan**')
                st.code(plan_text, language='text')
                st.markdown('**Query Results**')
                st.dataframe(results, hide_index=True, use_container_width=True)
            st.divider()
        st.subheader('Live Execution Time Comparison')
        rows = [{'Experiment': f'E{i}: {label}', 'Execution time (ms)': st.session_state['e1_results'][index][1]}
                for i, (label, index, _) in enumerate(configs, 1)
                if index in st.session_state['e1_results'] and st.session_state['e1_results'][index][1] is not None]
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True)
            st.bar_chart(df, x='Experiment', y='Execution time (ms)')
        else:
            st.caption('Run an experiment to display live timings.')
        st.caption('Each timing is a single EXPLAIN ANALYZE measurement, not an average or client-side elapsed time.')

    with c:
        st.subheader('E.2 Sorting and Join Experiment')
        df = pd.DataFrame({
            'Strategy': [
                'Full sort',
                'Top-N',
                'Early aggregation CTE'
            ],
            'Execution time (ms)': [193, 191, 96.9],
            'Join output': [100836, 100836, 10],
            'Main sort record bytes': [1080, 1080, 37],
            'Main sort peak bytes': [85712, 85712, 36560],
            'Disk spills': [0, 0, 0]
        })
        st.dataframe(df, hide_index=True)
        st.bar_chart(df, x='Strategy', y='Execution time (ms)')
        st.metric('Observed reduction vs Top-N', '49.27%')

    with d:
        st.subheader('E.2 Live Query Lab')
        st.caption(
            'Live experiments use the cloud database and its current indexes. '
            'Timings are not directly comparable with historical local measurements.'
        )

        strategy = st.radio(
            'Query strategy',
            ['Full sorting', 'Top-N', 'Early aggregation CTE'],
            key='e2_strategy'
        )
        minimum = st.number_input(
            'Minimum rating count',
            1, 100000, 50,
            key='lab_min'
        )
        n = st.slider('Top N', 1, 100, 10, key='lab_n')

        sql = CTE if strategy == 'Early aggregation CTE' else TOP + (
            ' LIMIT %s' if strategy == 'Top-N' else ''
        )
        params = (minimum,) if strategy == 'Full sorting' else (minimum, n)

        show_sql('EXPLAIN ANALYZE\n' + sql)

        if st.button('Run E.2 Live Experiment', key='run_e2'):
            st.subheader('Current ratings indexes')
            st.dataframe(
                run('SHOW INDEX FROM ratings', schema=database),
                hide_index=True
            )

            start = time.perf_counter()
            df = run(
                'EXPLAIN ANALYZE ' + sql,
                params,
                schema=database
            )
            elapsed = (time.perf_counter() - start) * 1000

            plan = '\n'.join(str(x) for x in df.iloc[:, 0])
            st.subheader('Execution Plan')
            st.code(plan, language='text')

            match = re.search(
                r'actual time=[\d.]+\.\.([\d.]+)',
                plan
            )
            if match:
                st.metric(
                    'Root iterator completion time',
                    match.group(1) + ' ms'
                )

            st.caption(
                f'Client elapsed time including connection and retrieval: '
                f'{elapsed:.1f} ms. No indexes are created or dropped.'
            )

    with e:
        st.subheader('E.3 Explicit Sorting vs. Index-Provided Ordering')

        df = pd.DataFrame({
            'Experiment': [
                'Without composite index',
                'With composite index'
            ],
            'Additional index': [
                'None',
                '(rating, movieId)'
            ],
            'Ratings access': [
                'Full table scan',
                'Covering index range scan'
            ],
            'Sorting operation': [
                'Explicit Sort',
                'No separate Sort'
            ],
            'Rows read from ratings': [100836, 20],
            'Rows satisfying filter': [
                '21,762',
                'Not fully evaluated'
            ],
            'Output rows': [20, 20],
            'Execution time (ms)': [62.4, 2.75]
        })

        st.dataframe(df, hide_index=True, use_container_width=True)
        st.bar_chart(df, x='Experiment', y='Execution time (ms)')
        st.metric('Observed execution time reduction', '95.59%')
        st.metric('Speedup', '22.69x')

        st.markdown(
            'The composite index on `(rating, movieId)` allows MySQL '
            'to retrieve records in the requested descending order without '
            'a separate sorting operation. Without the index, MySQL scans '
            'the ratings table and explicitly sorts the qualifying records. '
            'The optimizer trace for the first experiment also showed '
            '`std::stable_sort` and three initial sorting chunks spilled to disk.'
        )

        st.caption(
            'The indexed experiment stopped after retrieving 20 qualifying '
            'records because of LIMIT 20, so the total number of records '
            'satisfying the filter was not fully evaluated.'
        )

    with f:
        st.subheader('E.3 Live Query: Index-Provided Ordering')
        st.write(
            'This experiment compares explicit sorting with index-provided '
            'ordering, using the indexes already present in the cloud database. '
            'No indexes are created or dropped.'
        )

        index_df = run('SHOW INDEX FROM ratings', schema=database)
        index_names = set(index_df['Key_name'].astype(str))

        st.markdown('**Current ratings indexes**')
        st.dataframe(
            index_df,
            hide_index=True,
            use_container_width=True
        )

        existing_composite_indexes = [
            name for name in [
                'idx_ratings_movie_rating',
                'idx_ratings_rating_movie'
            ]
            if name in index_names
        ]

        ignore_hint = ''
        if existing_composite_indexes:
            ignore_hint = (
                ' IGNORE INDEX ('
                + ', '.join(existing_composite_indexes)
                + ')'
            )

        e3_sort_sql = f'''SELECT
    r.movieId,
    m.title,
    r.rating
FROM ratings r{ignore_hint}
JOIN movies m ON r.movieId = m.movieId
WHERE r.rating >= %s
ORDER BY r.rating DESC, r.movieId DESC
LIMIT 20'''

        e3_index_sql = '''SELECT
    r.movieId,
    m.title,
    r.rating
FROM ratings r FORCE INDEX (idx_ratings_rating_movie)
JOIN movies m ON r.movieId = m.movieId
WHERE r.rating >= %s
ORDER BY r.rating DESC, r.movieId DESC
LIMIT 20'''

        st.markdown('**Experiment 1: Explicit Sorting**')
        show_sql('EXPLAIN ANALYZE\n' + e3_sort_sql)

        if st.button('Run E.3 Explicit Sorting', key='run_e3_sort'):
            plan = run(
                'EXPLAIN ANALYZE ' + e3_sort_sql,
                (4.5,),
                schema=database
            )
            plan_text = '\n'.join(str(x) for x in plan.iloc[:, 0])
            st.subheader('Execution Plan: Explicit Sorting')
            st.code(plan_text, language='text')

            st.subheader('Query Results')
            results = run(e3_sort_sql, (4.5,), schema=database)
            st.dataframe(
                results,
                hide_index=True,
                use_container_width=True
            )

        st.divider()
        st.markdown('**Experiment 2: Index-Provided Ordering**')
        show_sql('EXPLAIN ANALYZE\n' + e3_index_sql)

        if 'idx_ratings_rating_movie' not in index_names:
            st.warning(
                'The index idx_ratings_rating_movie is not currently '
                'present in the cloud database. This query cannot be '
                'executed until that index is available. No index will '
                'be created automatically.'
            )
        elif st.button(
            'Run E.3 Index-Provided Ordering',
            key='run_e3_index'
        ):
            plan = run(
                'EXPLAIN ANALYZE ' + e3_index_sql,
                (4.5,),
                schema=database
            )
            plan_text = '\n'.join(str(x) for x in plan.iloc[:, 0])
            st.subheader('Execution Plan: Index-Provided Ordering')
            st.code(plan_text, language='text')

            st.subheader('Query Results')
            results = run(e3_index_sql, (4.5,), schema=database)
            st.dataframe(
                results,
                hide_index=True,
                use_container_width=True
            )

def query_processing():
    st.header('Query Processing')
    st.caption('How MySQL executes the Top 10 Highest-Rated Movies query')
    st.info('The execution statistics below are recorded observations from our project, not live database measurements.')
    a,b,c=st.columns(3)
    a.metric('Movies', '9,742'); b.metric('Joined records','100,836'); c.metric('Final results','10')
    st.header('Query 1 Objective')
    st.write('The purpose of query 1 is to identify the top 10 highest-rated movies that have received at least 50 ratings. The minimum rating count requirement reduces the influence of movies with very few ratings and provides a more meaningful ranking. This query demonstrates several important query processing operations discussed in class, including index-based access, nested loop joins, aggregation, and sorting.')
    show_sql('''SELECT m.movieId, m.title,
        COUNT(r.rating) AS rating_count,
        ROUND(AVG(r.rating), 2) AS average_rating
    FROM movies m
    JOIN ratings r ON m.movieId = r.movieId
    GROUP BY m.movieId, m.title
    HAVING COUNT(r.rating) >= 50
    ORDER BY average_rating DESC, rating_count DESC
    LIMIT 10;''')
    st.subheader('Query Explanation')
    st.write('It joins the `movies` and `ratings` tables using `movieId` and calculates the rating count and average rating for each movie.\n\nThe `HAVING` clause removes movies with fewer than 50 ratings. The remaining movies are sorted by average rating in descending order. If two movies have the same average rating, the movie with more ratings is ranked higher. Finally, the query returns the top 10 movies.\n\nThis query involves four important database operations discussed in class: index-based access, joining, aggregation, and sorting.')
    st.header('Query Execution Flow')
    st.graphviz_chart('''digraph { rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#E8F0FE", fontname="Arial"]; A [label="Movies scan: 9,742"]; B [label="B+ Tree index lookup: 9,742 iterations"]; C [label="Nested loop join: 100,836 records"]; D [label="Aggregation: 9,724 groups"]; E [label="HAVING: 450 groups"]; F [label="Sorting: average rating, rating count"]; G [label="LIMIT: 10 movies"]; A -> B -> C -> D -> E -> F -> G; }''')
    st.header('Physical Query Processing')

    with st.container():
        st.subheader("Index-Based Access")
        st.write('MySQL uses a B+ Tree index on `movieId` in the `ratings` table to find the corresponding ratings for each movie instead of scanning the entire table.\n\nFor each movie, MySQL uses its `movieId` as the search key. It starts from the root node of the B+ Tree, moves through the internal nodes, and reaches the leaf node containing the matching index entries.\n\nSince the index entries are sorted by `movieId`, MySQL can find the first matching entry and continue scanning nearby entries until the `movieId` changes.\n\nOnce MySQL finds the matching entries, it retrieves the corresponding rating values. If the rating values are not stored in the index, MySQL uses the primary key to access the original table records.\n\nFor example, if a movie has three ratings of 4.5, 5.0, and 3.5, MySQL retrieves these values for the following join and aggregation operations.')
        st.graphviz_chart('''digraph { node [shape=box]; R [label="Root: 30"]; L [label="Internal: 20"]; H [label="Internal: 40"]; A [label="10 | 10 | 10",style=filled,fillcolor="#D5EBD9"]; B [label="20 | 20"]; C [label="30 | 30"]; D [label="40"]; R -> L [color=green,penwidth=3]; R -> H; L -> A [color=green,penwidth=3]; L -> B; H -> C; H -> D; {rank=same; A B C D} A -> B -> C -> D [style=dashed,constraint=false]; }''')
        st.caption('Illustrative B+ Tree: search for movieId = 10, scan matching entries, then stop at 20.')
        st.table(pd.DataFrame({'Matching movieId':[10,10,10], 'Retrieved rating':[4.5,5.0,3.5]}))
    with st.container():
        st.subheader("Nested Loop Join")
        st.write('In the original query, MySQL performs a nested loop join between the `movies` and `ratings` tables.\n\n- **Outer relation:** `movies` (9,742 records).\n- **Inner relation:** `ratings`, accessed through the `movieId` index.\n- **Number of index lookup iterations:** 9,742.\n- **Join output:** 100,836 records.\n\nMySQL reads each movie from the outer table and uses the `movieId` index to find matching records in the inner table.\n\nFor example, if a movie has three ratings, MySQL combines the movie information with each rating and produces three joined records.\n\nMySQL repeats this process for all 9,742 movies and produces 100,836 joined records.')
        st.dataframe(pd.DataFrame({'movieId':[10]*3,'title':['Movie A']*3,'rating':[4.5,5.0,3.5]}),hide_index=True)
        st.caption('Illustrative join output.')
    with st.container():
        st.subheader("Aggregation")
        st.write('After joining the two tables, MySQL uses an internal temporary table to group the records by `movieId` and `title`.\n\nFor each movie, MySQL keeps track of the sum and count of its ratings to calculate the average rating.\n\nAccording to the execution plan, MySQL groups 100,836 joined records into 9,724 movie groups.\n\nThe `HAVING` clause then removes movies with fewer than 50 ratings, leaving 450 movie groups.')
        ratings=[4.5,5.0,3.5]
        n=st.slider('Number of example ratings processed',1,3,3)
        s=pd.Series(ratings[:n]); st.dataframe(pd.DataFrame({'Rating':s,'Running sum':s.cumsum(),'Running count':range(1,n+1)}),hide_index=True)
        x,y,z=st.columns(3); x.metric('SUM',f'{s.sum():.1f}'); y.metric('COUNT',n); z.metric('AVG',f'{s.mean():.2f}')
        st.caption('HAVING: this example is filtered out because it has fewer than 50 ratings.')
        st.caption('Illustrative example, not actual query results.')
    with st.container():
        st.subheader("Sorting")
        st.write('After aggregation and filtering, MySQL sorts the 450 remaining movie groups using two sorting keys:\n\n- `average_rating` in descending order.\n- `rating_count` in descending order.\n\nSince the average rating and rating count are calculated during aggregation, the existing index on `movieId` cannot directly provide the required sorting order. Therefore, MySQL needs to perform a separate sorting operation.\n\nFinally, the `LIMIT 10` clause returns the top 10 movies.')
    



try:
    if page=='Data Overview': overview()
    elif page=='Database': database_page()
    elif page=='Query Workload': queries()
    elif page=='Query Processing': query_processing()
    else: experiments()
except mysql.connector.Error as e:
    st.error('Database query failed. Please try again or contact the app administrator.')
